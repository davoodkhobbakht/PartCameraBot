import os
import sys
import datetime
import logging
import queue as queuem
import re
import threading
import traceback
import uuid
from html import escape
from typing import *

import requests
import sqlalchemy
import telegram

import database as db
import localization
import nuconfig

log = logging.getLogger(__name__)


class StopSignal:
    """A data class that should be sent to the worker when the conversation has to be stopped abnormally."""

    def __init__(self, reason: str = ""):
        self.reason = reason


class CancelSignal:
    """An empty class that is added to the queue whenever the user presses a cancel inline button."""
    pass


class Worker(threading.Thread):
    """A worker for a single conversation. A new one is created every time the /start command is sent."""

    def __init__(self,
                 bot,
                 chat: telegram.Chat,
                 telegram_user: telegram.User,
                 cfg: nuconfig.NuConfig,
                 engine,
                 *args,
                 **kwargs):
        # Initialize the thread
        super().__init__(name=f"Worker {chat.id}", *args, **kwargs)
        # Store the bot, chat info and config inside the class
        self.bot = bot
        self.chat: telegram.Chat = chat
        self.telegram_user: telegram.User = telegram_user
        self.cfg = cfg
        self.loc = None
        # Open a new database session
        log.debug(f"Opening new database session for {self.name}")
        self.session = sqlalchemy.orm.sessionmaker(bind=engine)()
        # Get the user db data from the users and admin tables
        self.user: Optional[db.User] = None
        self.admin: Optional[db.Admin] = None
        # The sending pipe is stored in the Worker class, allowing the forwarding of messages to the chat process
        self.queue = queuem.Queue()
        # The current active invoice payload; reject all invoices with a different payload
        self.invoice_payload = None
        # The price class of this worker.
        self.Price = self.price_factory()

    def __repr__(self):
        return f"<{self.__class__.__qualname__} {self.chat.id}>"

    # noinspection PyMethodParameters
    def price_factory(worker):
        class Price:
            """The base class for the prices in greed.
            Its int value is in minimum units, while its float and str values are in decimal format."""

            def __init__(self, value: Union[int, float, str, "Price"]):
                if isinstance(value, int):
                    # Keep the value as it is
                    self.value = int(value)
                elif isinstance(value, float):
                    # Convert the value to minimum units
                    self.value = int(value * (10 ** worker.cfg["Payments"]["currency_exp"]))
                elif isinstance(value, str):
                    # Remove decimal points, then cast to int
                    self.value = int(float(value.replace(",", ".")) * (10 ** worker.cfg["Payments"]["currency_exp"]))
                elif isinstance(value, Price):
                    # Copy self
                    self.value = value.value

            def __repr__(self):
                return f"<{self.__class__.__qualname__} of value {self.value}>"

            def __str__(self):
                return worker.loc.get(
                    "currency_format_string",
                    symbol=worker.cfg["Payments"]["currency_symbol"],
                    value="{0:.2f}".format(self.value / (10 ** worker.cfg["Payments"]["currency_exp"]))
                )

            def __int__(self):
                return self.value

            def __float__(self):
                return self.value / (10 ** worker.cfg["Payments"]["currency_exp"])

            def __ge__(self, other):
                return self.value >= Price(other).value

            def __le__(self, other):
                return self.value <= Price(other).value

            def __eq__(self, other):
                return self.value == Price(other).value

            def __gt__(self, other):
                return self.value > Price(other).value

            def __lt__(self, other):
                return self.value < Price(other).value

            def __add__(self, other):
                return Price(self.value + Price(other).value)

            def __sub__(self, other):
                return Price(self.value - Price(other).value)

            def __mul__(self, other):
                return Price(int(self.value * other))

            def __floordiv__(self, other):
                return Price(int(self.value // other))

            def __radd__(self, other):
                return self.__add__(other)

            def __rsub__(self, other):
                return Price(Price(other).value - self.value)

            def __rmul__(self, other):
                return self.__mul__(other)

            def __iadd__(self, other):
                self.value += Price(other).value
                return self

            def __isub__(self, other):
                self.value -= Price(other).value
                return self

            def __imul__(self, other):
                self.value *= other
                self.value = int(self.value)
                return self

            def __ifloordiv__(self, other):
                self.value //= other
                return self

        return Price

    def __create_localization(self):
        # Check if the user's language is enabled; if it isn't, change it to the default
        if self.user.language not in self.cfg["Language"]["enabled_languages"]:
            log.debug(f"User's language '{self.user.language}' is not enabled, changing it to the default")
            
    def run(self):
        """The conversation code."""
        log.debug("Starting conversation")
        # Get the user db data from the users and admin tables
        self.user = self.session.query(db.User).filter(db.User.user_id == self.chat.id).one_or_none()
        self.admin = self.session.query(db.Admin).filter(db.Admin.user_id == self.chat.id).one_or_none()
        # If the user isn't registered, create a new record and add it to the db
        if self.user is None:
            # Check if there are other registered users: if there aren't any, the first user will be owner of the bot
            will_be_owner = (self.session.query(db.Admin).first() is None)
            # Create the new record
            self.user = db.User(w=self)
            # Add the new record to the db
            self.session.add(self.user)
            # If the will be owner flag is set
            if will_be_owner:
                # Become owner
                self.admin = db.Admin(user=self.user,
                                      edit_products=True,
                                      receive_orders=True,
                                      create_transactions=True,
                                      display_on_help=True,
                                      is_owner=True,
                                      live_mode=False)
                # Add the admin to the transaction
                self.session.add(self.admin)
            # Commit the transaction
            self.session.commit()
            log.info(f"Created new user: {self.user}")
            if will_be_owner:
                log.warning(f"User was auto-promoted to Admin as no other admins existed: {self.user}")
        # Create the localization object
        self.__create_localization()
        # Capture exceptions that occour during the conversation
        # noinspection PyBroadException
        try:
            # Welcome the user to the bot
            if self.cfg["Appearance"]["display_welcome_message"] == "yes":
                self.bot.send_message(self.chat.id, self.loc.get("conversation_after_start"))
            # If the user is not an admin, send him to the user menu
            if self.admin is None:
                self.__user_menu()
            # If the user is an admin, send him to the admin menu
            else:
                # Clear the live orders flag
                self.admin.live_mode = False
                # Commit the change
                self.session.commit()
                # Open the admin menu
                self.__admin_menu()
        except Exception as e:
            # Try to notify the user of the exception
            # noinspection PyBroadException
            try:
                self.bot.send_message(self.chat.id, self.loc.get("fatal_conversation_exception"))
            except Exception as ne:
                log.error(f"Failed to notify the user of a conversation exception: {ne}")
            log.error(f"Exception in {self}: {e}")
            traceback.print_exception(*sys.exc_info())

    def is_ready(self):
        # Change this if more parameters are added!
        return self.loc is not None

    def stop(self, reason: str = ""):
        """Gracefully stop the worker process"""
        # Send a stop message to the thread
        self.queue.put(StopSignal(reason))
        # Wait for the thread to stop
        self.join()

    def update_user(self) -> db.User:
        """Update the user data."""
        log.debug("Fetching updated user data from the database")
        self.user = self.session.query(db.User).filter(db.User.user_id == self.chat.id).one_or_none()
        return self.user

    # noinspection PyUnboundLocalVariable
    def __receive_next_update(self) -> telegram.Update:
        """Get the next update from the queue.
        If no update is found, block the process until one is received.
        If a stop signal is sent, try to gracefully stop the thread."""
        # Pop data from the queue
        try:
            data = self.queue.get(timeout=self.cfg["Telegram"]["conversation_timeout"])
        except queuem.Empty:
            # If the conversation times out, gracefully stop the thread
            self.__graceful_stop(StopSignal("timeout"))
        # Check if the data is a stop signal instance
        if isinstance(data, StopSignal):
            # Gracefully stop the process
            self.__graceful_stop(data)
        # Return the received update
        return data

    def __wait_for_specific_message(self,
                                    items: List[str],
                                    cancellable: bool = False) -> Union[str, CancelSignal]:
        """Continue getting updates until until one of the strings contained in the list is received as a message."""
        log.debug("Waiting for a specific message...")
        while True:
            # Get the next update
            update = self.__receive_next_update()
            # If a CancelSignal is received...
            if isinstance(update, CancelSignal):
                # And the wait is cancellable...
                if cancellable:
                    # Return the CancelSignal
                    return update
                else:
                    # Ignore the signal
                    continue
            # Ensure the update contains a message
            if update.message is None:
                continue
            # Ensure the message contains text
            if update.message.text is None:
                continue
            # Check if the message is contained in the list
            if update.message.text not in items:
                continue
            # Return the message text
            return update.message.text

    def __wait_for_regex(self, regex: str, cancellable: bool = False) -> Union[str, CancelSignal]:
        """Continue getting updates until the regex finds a match in a message, then return the first capture group."""
        log.debug("Waiting for a regex...")
        while True:
            # Get the next update
            update = self.__receive_next_update()
            # If a CancelSignal is received...
            if isinstance(update, CancelSignal):
                # And the wait is cancellable...
                if cancellable:
                    # Return the CancelSignal
                    return update
                else:
                    # Ignore the signal
                    continue
            # Ensure the update contains a message
            if update.message is None:
                continue
            # Ensure the message contains text
            if update.message.text is None:
                continue
            # Try to match the regex with the received message
            match = re.search(regex, update.message.text, re.DOTALL)
            # Ensure there is a match
            if match is None:
                continue
            # Return the first capture group
            return match.group(1)

    def __wait_for_photo(self, cancellable: bool = False) -> Union[List[telegram.PhotoSize], CancelSignal]:
        """Continue getting updates until a photo is received, then return it."""
        log.debug("Waiting for a photo...")
        while True:
            # Get the next update
            update = self.__receive_next_update()
            # If a CancelSignal is received...
            if isinstance(update, CancelSignal):
                # And the wait is cancellable...
                if cancellable:
                    # Return the CancelSignal
                    return update
                else:
                    # Ignore the signal
                    continue
            # Ensure the update contains a message
            if update.message is None:
                continue
            # Ensure the message contains a photo
            if update.message.photo is None:
                continue
            # Return the photo array
            return update.message.photo

    def __wait_for_inlinekeyboard_callback(self, cancellable: bool = False) \
            -> Union[telegram.CallbackQuery, CancelSignal]:
        """Continue getting updates until an inline keyboard callback is received, then return it."""
        log.debug("Waiting for a CallbackQuery...")
        while True:
            # Get the next update
            update = self.__receive_next_update()
            # If a CancelSignal is received...
            if isinstance(update, CancelSignal):
                # And the wait is cancellable...
                if cancellable:
                    # Return the CancelSignal
                    return update
                else:
                    # Ignore the signal
                    continue
            # Ensure the update is a CallbackQuery
            if update.callback_query is None:
                continue
            # Answer the callbackquery
            self.bot.answer_callback_query(update.callback_query.id)
            # Return the callbackquery
            return update.callback_query

    def __user_select(self) -> Union[db.User, CancelSignal]:
        """Select an user from the ones in the database."""
        log.debug("Waiting for a user selection...")
        # Find all the users in the database
        users = self.session.query(db.User).order_by(db.User.user_id).all()
        # Create a list containing all the keyboard button strings
        keyboard_buttons = [[self.loc.get("menu_cancel")]]
        # Add to the list all the users
        for user in users:
            keyboard_buttons.append([user.identifiable_str()])
        # Create the keyboard
        keyboard = telegram.ReplyKeyboardMarkup(keyboard_buttons, one_time_keyboard=True)
        # Keep asking until a result is returned
        while True:
            # Send the keyboard
            self.bot.send_message(self.chat.id, self.loc.get("conversation_admin_select_user"), reply_markup=keyboard)
            # Wait for a reply
            reply = self.__wait_for_regex("user_([0-9]+)", cancellable=True)
            # Propagate CancelSignals
            if isinstance(reply, CancelSignal):
                return reply
            # Find the user in the database
            user = self.session.query(db.User).filter_by(user_id=int(reply)).one_or_none()
            # Ensure the user exists
            if not user:
                self.bot.send_message(self.chat.id, self.loc.get("error_user_does_not_exist"))
                continue
            return user

    def __user_menu(self):
        """Function called from the run method when the user is not an administrator.
        Normal bot actions should be placed here."""
        log.debug("Displaying __user_menu")
        # Loop used to returning to the menu after executing a command
        while True:
            # Create a keyboard with the user main menu
            keyboard = [[telegram.KeyboardButton(self.loc.get("menu_order"))],
                        [telegram.KeyboardButton(self.loc.get("menu_order_status"))],
                        [telegram.KeyboardButton(self.loc.get("menu_add_credit"))],
                        [telegram.KeyboardButton(self.loc.get("menu_help")),
                         telegram.KeyboardButton(self.loc.get("menu_bot_info"))]]
            # Send the previously created keyboard to the user (ensuring it can be clicked only 1 time)
            self.bot.send_message(self.chat.id,
                                  self.loc.get("conversation_open_user_menu",
                                               credit=self.Price(self.user.credit)),
                                  reply_markup=telegram.ReplyKeyboardMarkup(keyboard, one_time_keyboard=True))
            # Wait for a reply from the user
            selection = self.__wait_for_specific_message([
                self.loc.get("menu_order"),
                self.loc.get("menu_order_status"),
                self.loc.get("menu_help"),
                self.loc.get("menu_bot_info"),
            ])
            # After the user reply, update the user data
            self.update_user()
            # If the user has selected the Order option...
            if selection == self.loc.get("menu_order"):
                # Open the order menu
                self.__order_menu()
            # If the user has selected the Order Status option...
            elif selection == self.loc.get("menu_order_status"):
                # Display the order(s) status
                self.__order_status()
            # If the user has selected the Bot Info option...
            elif selection == self.loc.get("menu_bot_info"):
                # Display information about the bot
                self.__bot_info()
            # If the user has selected the Help option...
            elif selection == self.loc.get("menu_help"):
                # Go to the Help menu
                self.__help_menu()

    def __text_order_process(self):
        """Handle the text order process."""
        # Step 1: Ask for custom text
        self.bot.send_message(
            self.chat.id,
            "📝 لطفاً متن مورد نظر خود را برای تابلو نئون وارد کنید:"
        )
        custom_text = self.__wait_for_regex(r"(.+)", cancellable=True)
        
        if isinstance(custom_text, CancelSignal):
            self.bot.send_message(self.chat.id, "❌ سفارش لغو شد.")
            return
        
        # Step 2: Ask for font
        font_keyboard = telegram.InlineKeyboardMarkup([
            [telegram.InlineKeyboardButton("فونت ۱", callback_data="font1")],
            [telegram.InlineKeyboardButton("ب تیتر دو خط", callback_data="font2")],
            [telegram.InlineKeyboardButton("فونت ۳", callback_data="font3")],
        ])
        self.bot.send_message(
            self.chat.id,
            "🔤 لطفاً فونت مورد نظر خود را انتخاب کنید:",
            reply_markup=font_keyboard
        )
        font_callback = self.__wait_for_inlinekeyboard_callback()
        font_choice = font_callback.data
        
        # Step 3: Generate and send PDF
        self.bot.send_message(self.chat.id, "📄 در حال پردازش سفارش شما...")
        pdf_path = self.__generate_text_pdf(custom_text, font_choice)
        self.bot.send_document(self.chat.id, open(pdf_path, "rb"))
        
        
        order = db.Order(
            user=self.user,
            creation_date=datetime.datetime.now(),
            notes=f"سفارش متن: {custom_text}",
        )
        self.session.add(order)
        self.session.commit()
        # Step 4: Notify admins
        admin_ids = self.session.query(db.Admin.user_id).all()
        for admin_id in admin_ids:
            self.bot.send_document(admin_id[0], open(pdf_path, "rb"))
        
        self.bot.send_message(self.chat.id, "✅ سفارش شما ثبت شد و به مدیران ارسال گردید.")


    '''
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfbase import pdfmetrics
    from bidi.algorithm import get_display
    import arabic_reshaper

    def __generate_text_pdf(text, font_choice, font_size=18, page_size=(595.27, 841.89)):
        """
        Create a PDF file with Farsi text.

        :param output_path: Path to save the PDF
        :param text: Farsi text to render
        :param font_path: Path to a TTF font that supports Farsi
        :param font_name: Name to register the custom font
        :param font_size: Font size for the text
        :param page_size: Page size (default is A4)
        """
        # Register the Farsi font
        font_name = font_choice
        font_path = {
            "font2": "fonts/BTitrBd.ttf",
        }.get(font_choice, "onts/BTitrBd.ttf")
        pdfmetrics.registerFont(TTFont(font_name, font_path))
        output_path = f"/tmp/text_order_{uuid.uuid4().hex}.pdf"
        # Create a PDF canvas
        pdf = canvas.Canvas(output_path, pagesize=page_size)
        
        # Prepare the Farsi text
        reshaped_text = arabic_reshaper.reshape(text)
        bidi_text = get_display(reshaped_text)
        
        # Set the font and size
        pdf.setFont(font_name, font_size)
        
        # Write text to the PDF (centered)
        pdf.drawCentredString(page_size[0] / 2, page_size[1] / 2, bidi_text)
        
        # Save the PDF
        pdf.save()
        print(f"PDF file saved at: {output_path}")
        return output_path
    '''

    def __order_type_selection(self):
        """Ask user whether they want to order a product or a custom text."""
        # Inline keyboard for selecting order type
        order_type_keyboard = telegram.InlineKeyboardMarkup([
            [telegram.InlineKeyboardButton("📦 انتخاب از محصولات", callback_data="order_product")],
            [telegram.InlineKeyboardButton("📝 سفارش متن", callback_data="order_text")],
        ])
        self.bot.send_message(
            self.chat.id,
            "لطفاً نوع سفارش خود را انتخاب کنید:",
            reply_markup=order_type_keyboard
        )
        # Wait for user selection
        order_type_callback = self.__wait_for_inlinekeyboard_callback()
        return order_type_callback.data
    
    def __order_menu(self):
        """User menu to order products from the shop."""
        # Determine order type
        order_type = self.__order_type_selection()

        if order_type == "order_text":
            self.__text_order_process()
            return  # Exit after handling text order
        # Continue with product selection for "order_product"
        log.debug("Displaying __order_menu")
        # Get the products list from the db
        products = self.session.query(db.Product).filter_by(deleted=False).all()
        # Create a dict to be used as 'cart'
        # The key is the message id of the product list
        cart: Dict[List[db.Product, int]] = {}
        # Initialize the products list
        for product in products:
            # If the product is not for sale, don't display it
            if product.price is None:
                continue
            # Send the message without the keyboard to get the message id
            message = product.send_as_message(w=self, chat_id=self.chat.id)
            # Add the product to the cart
            cart[message['message_id']] = [product, 0]
            # Create the inline keyboard to add the product to the cart
            inline_keyboard = telegram.InlineKeyboardMarkup(
                [[telegram.InlineKeyboardButton(self.loc.get("menu_add_to_cart"), callback_data="cart_add")]]
            )
            # Edit the sent message and add the inline keyboard
            if product.image is None:
                self.bot.edit_message_text(chat_id=self.chat.id,
                                           message_id=message['message_id'],
                                           text=product.text(w=self),
                                           reply_markup=inline_keyboard)
                
                
            else:
                self.bot.edit_message_caption(chat_id=self.chat.id,
                                              message_id=message['message_id'],
                                              caption=product.text(w=self),
                                              reply_markup=inline_keyboard)
                
        # Create the keyboard with the cancel button
        inline_keyboard = telegram.InlineKeyboardMarkup([[telegram.InlineKeyboardButton(self.loc.get("menu_cancel"),
                                                                                        callback_data="cart_cancel")]])
        # Send a message containing the button to cancel or pay
        final_msg = self.bot.send_message(self.chat.id,
                                          self.loc.get("conversation_cart_actions"),
                                          reply_markup=inline_keyboard)
        # Wait for user input
        while True:
            callback = self.__wait_for_inlinekeyboard_callback()
            # React to the user input
            # If the cancel button has been pressed...
            if callback.data == "cart_cancel":
                # Stop waiting for user input and go back to the previous menu
                return
            # If a Add to Cart button has been pressed...
            elif callback.data == "cart_add":
                # Get the selected product, ensuring it exists
                p = cart.get(callback.message.message_id)
                if p is None:
                    continue
                product = p[0]
                # Add 1 copy to the cart
                cart[callback.message.message_id][1] += 1
                # Create the product inline keyboard
                product_inline_keyboard = telegram.InlineKeyboardMarkup(
                    [
                        [telegram.InlineKeyboardButton(self.loc.get("menu_add_to_cart"),
                                                       callback_data="cart_add"),
                         telegram.InlineKeyboardButton(self.loc.get("menu_remove_from_cart"),
                                                       callback_data="cart_remove")]
                    ])
                # Create the final inline keyboard
                final_inline_keyboard = telegram.InlineKeyboardMarkup(
                    [
                        [telegram.InlineKeyboardButton(self.loc.get("menu_cancel"), callback_data="cart_cancel")],
                        [telegram.InlineKeyboardButton(self.loc.get("menu_done"), callback_data="cart_done")]
                    ])
                # Edit both the product and the final message
                if product.image is None:
                    self.bot.edit_message_text(chat_id=self.chat.id,
                                               message_id=callback.message.message_id,
                                               text=product.text(w=self,
                                                                 cart_qty=cart[callback.message.message_id][1]),
                                               reply_markup=product_inline_keyboard)
                else:
                    self.bot.edit_message_caption(chat_id=self.chat.id,
                                                  message_id=callback.message.message_id,
                                                  caption=product.text(w=self,
                                                                       cart_qty=cart[callback.message.message_id][1]),
                                                  reply_markup=product_inline_keyboard)

                self.bot.edit_message_text(
                    chat_id=self.chat.id,
                    message_id=final_msg.message_id,
                    text=self.loc.get("conversation_confirm_cart",
                                      product_list=self.__get_cart_summary(cart),
                                      total_cost=str(self.__get_cart_value(cart))),
                    reply_markup=final_inline_keyboard)
            # If the Remove from cart button has been pressed...
            elif callback.data == "cart_remove":
                # Get the selected product, ensuring it exists
                p = cart.get(callback.message.message_id)
                if p is None:
                    continue
                product = p[0]
                # Remove 1 copy from the cart
                if cart[callback.message.message_id][1] > 0:
                    cart[callback.message.message_id][1] -= 1
                else:
                    continue
                # Create the product inline keyboard
                product_inline_list = [[telegram.InlineKeyboardButton(self.loc.get("menu_add_to_cart"),
                                                                      callback_data="cart_add")]]
                if cart[callback.message.message_id][1] > 0:
                    product_inline_list[0].append(telegram.InlineKeyboardButton(self.loc.get("menu_remove_from_cart"),
                                                                                callback_data="cart_remove"))
                product_inline_keyboard = telegram.InlineKeyboardMarkup(product_inline_list)
                # Create the final inline keyboard
                final_inline_list = [[telegram.InlineKeyboardButton(self.loc.get("menu_cancel"),
                                                                    callback_data="cart_cancel")]]
                for product_id in cart:
                    if cart[product_id][1] > 0:
                        final_inline_list.append([telegram.InlineKeyboardButton(self.loc.get("menu_done"),
                                                                                callback_data="cart_done")])
                        break
                final_inline_keyboard = telegram.InlineKeyboardMarkup(final_inline_list)
                # Edit the product message
                if product.image is None:
                    self.bot.edit_message_text(chat_id=self.chat.id, message_id=callback.message.message_id,
                                               text=product.text(w=self,
                                                                 cart_qty=cart[callback.message.message_id][1]),
                                               reply_markup=product_inline_keyboard)
                else:
                    self.bot.edit_message_caption(chat_id=self.chat.id,
                                                  message_id=callback.message.message_id,
                                                  caption=product.text(w=self,
                                                                       cart_qty=cart[callback.message.message_id][1]),
                                                  reply_markup=product_inline_keyboard)

                self.bot.edit_message_text(
                    chat_id=self.chat.id,
                    message_id=final_msg.message_id,
                    text=self.loc.get("conversation_confirm_cart",
                                      product_list=self.__get_cart_summary(cart),
                                      total_cost=str(self.__get_cart_value(cart))),
                    reply_markup=final_inline_keyboard)
            # If the done button has been pressed...
            elif callback.data == "cart_done":
                # End the loop
                break
        # Create an inline keyboard with a single skip button
        cancel = telegram.InlineKeyboardMarkup([[telegram.InlineKeyboardButton(self.loc.get("menu_skip"),
                                                                               callback_data="cmd_cancel")]])
        # Ask if the user wants to add notes to the order
        self.bot.send_message(self.chat.id, self.loc.get("ask_order_notes"),)
        # Wait for user input
        notes = self.__wait_for_regex(r"(.*)", cancellable=True)
        # Create a new Order
        order = db.Order(user=self.user,
                         creation_date=datetime.datetime.now(),
                         notes=notes if not isinstance(notes, CancelSignal) else "")
        # Add the record to the session and get an ID
        self.session.add(order)
        # For each product added to the cart, create a new OrderItem
        for product in cart:
            # Create {quantity} new OrderItems
            for i in range(0, cart[product][1]):
                order_item = db.OrderItem(product=cart[product][0],
                                          order=order)
                self.session.add(order_item)

        self.bot.send_message(self.chat.id, self.loc.get("ask_payment_image"))
        # Wait for an answer
        payment_photo = self.__wait_for_photo(cancellable=False)

        
        # Get the file object associated with the photo
        photo_file = self.bot.get_file(payment_photo[0].file_id)
        # Notify the user that the bot is downloading the image and might be inactive for a while
        self.bot.send_message(self.chat.id, self.loc.get("downloading_image"))
        self.bot.send_chat_action(self.chat.id, action="upload_photo")
        # Set the image for that product
        order.set_image(photo_file)
        # Commit the session changes
        self.session.commit()
        self.__order_transaction(order=order, value=-int(self.__get_cart_value(cart)))






    def ask_user_info(self):
        # Ask for user's name
        self.bot.send_message(self.chat.id, "👤 لطفا نام خود را وارد کنید:")
        name = self.__wait_for_regex(r".+", cancellable=True)

        # Ask for birth date
        self.bot.send_message(self.chat.id, "📅 لطفا تاریخ تولد خود را وارد کنید (مثلا 1400/01/01):")
        birth_date = self.__wait_for_regex(r"\d{4}/\d{2}/\d{2}", cancellable=True)

        # Ask for contact information
        self.bot.send_message(self.chat.id, "📞 شماره تماس خود را وارد کنید:")
        phone = self.__wait_for_regex(r"(\+98|0)\d{10}", cancellable=True)

        return {"name": name, "birth_date": birth_date, "phone": phone}

    def ask_board_details(self):
        # Inline keyboard for shape selection
        shape_keyboard = telegram.InlineKeyboardMarkup([
            [telegram.InlineKeyboardButton("🔵 دایره", callback_data="shape_circle")],
            [telegram.InlineKeyboardButton("🔶 لوزی", callback_data="shape_diamond")],
            [telegram.InlineKeyboardButton("⬛ مربع", callback_data="shape_square")],
            [telegram.InlineKeyboardButton("🔲 مستطیل", callback_data="shape_rectangle")]
        ])
        self.bot.send_message(self.chat.id, "📐 شکل تابلو مورد نظر خود را انتخاب کنید:", reply_markup=shape_keyboard)
        shape_callback = self.__wait_for_inlinekeyboard_callback()
        shape = shape_callback.data

        # Ask for dimensions
        self.bot.send_message(self.chat.id, "📏 طول تابلو را وارد کنید (به سانتی‌متر):")
        length = self.__wait_for_regex(r"\d+", cancellable=True)
        self.bot.send_message(self.chat.id, "دقت کنید که نسبت طول عرض متناسب با طرح خود انتخاب کنید . 📏 عرض تابلو را وارد کنید (به سانتی‌متر):")
        width = self.__wait_for_regex(r"\d+", cancellable=True)

        return {"shape": shape, "length": length, "width": width}


    def ask_color_details(self):
        # Inline keyboard for shape selection
        shape_keyboard = telegram.InlineKeyboardMarkup([
            [telegram.InlineKeyboardButton("🔵 دایره", callback_data="shape_circle")],
            [telegram.InlineKeyboardButton("🔶 لوزی", callback_data="shape_diamond")],
            [telegram.InlineKeyboardButton("⬛ مربع", callback_data="shape_square")],
            [telegram.InlineKeyboardButton("🔲 مستطیل", callback_data="shape_rectangle")]
        ])
        self.bot.send_message(self.chat.id, " رنگ تابلو را انتخاب کنید", reply_markup=shape_keyboard)
        shape_callback = self.__wait_for_inlinekeyboard_callback()
        shape = shape_callback.data

        # Ask for dimensions

        self.bot.send_message(self.chat.id, "📏 طول تابلو را وارد کنید (به سانتی‌متر):")
        length = self.__wait_for_regex(r"\d+", cancellable=True)
        self.bot.send_message(self.chat.id, "دقت کنید که نسبت طول عرض متناسب با طرح خود انتخاب کنید . 📏 عرض تابلو را وارد کنید (به سانتی‌متر):")
        width = self.__wait_for_regex(r"\d+", cancellable=True)

        return {"shape": shape, "length": length, "width": width}



    def ask_delivery_options(self):
        # Inline keyboard for delivery method
        delivery_keyboard = telegram.InlineKeyboardMarkup([
            [telegram.InlineKeyboardButton("🚚 پست", callback_data="delivery_postal")],
            [telegram.InlineKeyboardButton("📦 مستقیم", callback_data="delivery_direct")]
        ])
        self.bot.send_message(self.chat.id, "روش ارسال را انتخاب کنید:", reply_markup=delivery_keyboard)
        delivery_callback = self.__wait_for_inlinekeyboard_callback()
        delivery_method = delivery_callback.data

        return {"delivery_method": delivery_method}
    def ask_background_color(self):
        # Inline keyboard for background color selection (based on the form)
        color_keyboard = telegram.InlineKeyboardMarkup([
            [telegram.InlineKeyboardButton("⚪ سفید", callback_data="color_white"),
            telegram.InlineKeyboardButton("⚫ مشکی", callback_data="color_black")]
        ])

        # Send the message with the color options
        self.bot.send_message(self.chat.id, "🎨 لطفاً رنگ پس‌زمینه تابلو را انتخاب کنید:", reply_markup=color_keyboard)
        
        # Wait for user to select a color
        color_callback = self.__wait_for_inlinekeyboard_callback()
        color = color_callback.data

        # Map the callback data to color names
        color_mapping = {
            "color_white": "سفید",
            "color_black": "مشکی"
        }
        
        return color_mapping[color]


    def ask_hanger_option(self):
        # Inline keyboard for hanger selection
        hanger_keyboard = telegram.InlineKeyboardMarkup([
            [telegram.InlineKeyboardButton("✅ بله", callback_data="hanger_yes"),
            telegram.InlineKeyboardButton("❌ خیر", callback_data="hanger_no")]
        ])

        # Ask user about hanger
        self.bot.send_message(self.chat.id, "آیا تابلو جا آویز داشته باشد؟", reply_markup=hanger_keyboard)
        
        # Wait for user response
        hanger_callback = self.__wait_for_inlinekeyboard_callback()
        return "بله" if hanger_callback.data == "hanger_yes" else "خیر"


    def ask_border_option(self):
        # Inline keyboard for border selection
        border_keyboard = telegram.InlineKeyboardMarkup([
            [telegram.InlineKeyboardButton("✅ بله", callback_data="border_yes"),
            telegram.InlineKeyboardButton("❌ خیر", callback_data="border_no")]
        ])

        # Ask user about border
        self.bot.send_message(self.chat.id, "آیا تابلو دورگیری شود؟", reply_markup=border_keyboard)
        
        # Wait for user response
        border_callback = self.__wait_for_inlinekeyboard_callback()
        return "بله" if border_callback.data == "border_yes" else "خیر"

    def ask_neon_color(self):
        # Inline keyboard for neon color selection
        neon_color_keyboard = telegram.InlineKeyboardMarkup([
            [
                telegram.InlineKeyboardButton("🔴 قرمز", callback_data="neon_red"),
                telegram.InlineKeyboardButton("🔵 آبی", callback_data="neon_blue"),
            ],
            [
                telegram.InlineKeyboardButton("🟢 سبز", callback_data="neon_green"),
                telegram.InlineKeyboardButton("🟠 نارنجی", callback_data="neon_orange"),
            ],
            [
                telegram.InlineKeyboardButton("⚪ سفید", callback_data="neon_white")
            ]
        ])

        # Send the message with neon color options
        self.bot.send_message(self.chat.id, "💡 لطفاً رنگ نئون تابلو را انتخاب کنید:", reply_markup=neon_color_keyboard)
        
        # Wait for user to select a color
        neon_color_callback = self.__wait_for_inlinekeyboard_callback()
        neon_color = neon_color_callback.data

        # Map the callback data to color names
        neon_color_mapping = {
            "neon_red": "قرمز",
            "neon_blue": "آبی",
            "neon_green": "سبز",
            "neon_orange": "نارنجی",
            "neon_white": "سفید",
        }

        return neon_color_mapping[neon_color]
    def ask_flash_and_adapter(self):
        # Inline keyboard for flasher and adapter options
        flash_adapter_keyboard = telegram.InlineKeyboardMarkup([
            [
                telegram.InlineKeyboardButton("✅ نیاز به فلاشر دارم", callback_data="flash_yes"),
                telegram.InlineKeyboardButton("❌ نیازی به فلاشر ندارم", callback_data="flash_no"),
            ],
            [
                telegram.InlineKeyboardButton("✅ نیاز به آداپتور دارم", callback_data="adapter_yes"),
                telegram.InlineKeyboardButton("❌ نیازی به آداپتور ندارم", callback_data="adapter_no"),
            ],
        ])

        # Send message with flasher and adapter options
        self.bot.send_message(self.chat.id, "لطفاً مشخص کنید که آیا به فلاشر و آداپتور نیاز دارید:", reply_markup=flash_adapter_keyboard)

        # Wait for user to select
        flash_adapter_callback = self.__wait_for_inlinekeyboard_callback()
        flash_or_adapter = flash_adapter_callback.data

        # Map callback data to user-friendly names
        flash_adapter_mapping = {
            "flash_yes": "نیاز به فلاشر دارد",
            "flash_no": "نیاز به فلاشر ندارد",
            "adapter_yes": "نیاز به آداپتور دارد",
            "adapter_no": "نیاز به آداپتور ندارد",
        }

        return flash_adapter_mapping[flash_or_adapter]


    def collect_order(self):
        # Personal Info
        user_info = self.ask_user_info()

        # Board Details
        board_details = self.ask_board_details()

        # Background Color
        background_color = self.ask_background_color()

        # Neon Color
        neon_color = self.ask_neon_color()

        # Hanger Option
        hanger_option = self.ask_hanger_option()

        # Border Option
        border_option = self.ask_border_option()

        # Flash and Adapter Options
        flash_option = self.ask_flash_and_adapter()

        # Delivery Options
        delivery_options = self.ask_delivery_options()

        # Combine all information
        order = {
            **user_info,
            **board_details,
            "background_color": background_color,
            "neon_color": neon_color,
            "hanger": hanger_option,
            "border": border_option,
            "flash_adapter": flash_option,
            **delivery_options
        }

        # Confirm order
        order_summary = (
            f"👤 نام: {order['name']}\n"
            f"📅 تاریخ تولد: {order['birth_date']}\n"
            f"📞 شماره تماس: {order['phone']}\n"
            f"📐 شکل تابلو: {order['shape']}\n"
            f"📏 ابعاد: {order['length']}x{order['width']} سانتی‌متر\n"
            f"🎨 رنگ پس‌زمینه: {order['background_color']}\n"
            f"💡 رنگ نئون: {order['neon_color']}\n"
            f"🪝 جا آویز: {order['hanger']}\n"
            f"🖌️ دورگیری: {order['border']}\n"
            f"💡 فلاشر و آداپتور: {order['flash_adapter']}\n"
            f"🚚 روش ارسال: {order['delivery_method']}"
        )
        self.bot.send_message(self.chat.id, f"سفارش شما:\n{order_summary}\nلطفا تایید کنید.")

        # Wait for user confirmation
        confirmation = self.__wait_for_regex(r"(تایید|لغو)", cancellable=True)

        if confirmation == "تایید":
            # Redirect to payment
            self.bot.send_message(self.chat.id, self.loc.get("ask_payment_image"))
            # Wait for an answer
            payment_photo = self.__wait_for_photo(cancellable=False)

            
            # Get the file object associated with the photo
            photo_file = self.bot.get_file(payment_photo[0].file_id)
            # Notify the user that the bot is downloading the image and might be inactive for a while
            self.bot.send_message(self.chat.id, self.loc.get("downloading_image"))
            self.bot.send_chat_action(self.chat.id, action="upload_photo")

            order = db.Order(user=self.user,
                         creation_date=datetime.datetime.now(),
                         notes=order_summary )
            order.set_image(photo_file)
            self.session.add(order)

            # Commit the session changes
            self.session.commit()
            self.__order_transaction(order=order, value=-int(self.__get_cart_value(cart)))

            
        else:
            # Cancel the order
            self.bot.send_message(self.chat.id, "❌ سفارش شما لغو شد.")


    def redirect_to_payment(self, order):
        # Payment message
        self.bot.send_message(self.chat.id, "✅ سفارش شما ثبت شد.\nلطفاً برای پرداخت به لینک زیر مراجعه کنید:")
        
        # Generate a payment link (Example URL - replace with your actual payment system)
        payment_link = "https://example.com/payment?order_id=12345"
        self.bot.send_message(self.chat.id, f"💳 [پرداخت آنلاین]({payment_link})", parse_mode="Markdown")

        # After payment, confirm to the user
        self.bot.send_message(self.chat.id, "💡 پس از پرداخت، سفارش شما پردازش خواهد شد. متشکریم!")
