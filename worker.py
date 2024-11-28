import json
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
from PIL import Image, ImageDraw, ImageFont

from fpdf import FPDF
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
                 start_args=None,
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
        self.start_args = start_args 
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
                    value="{0:.0f}".format(self.value / (10 ** worker.cfg["Payments"]["currency_exp"]))
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

    def __is_user_following_channel(self):
        """Check if the user is following the channel."""
        channel_username = "lampinoshop"
        try:
            status = self.bot.get_chat_member(f"@{channel_username}", self.chat.id).status
            return status in ["member", "administrator", "creator"]
        except telegram.error.BadRequest:
            # User may not exist or bot isn't an admin in the channel
            return False

    def __recommend_channel(self):
        """Recommend the user to follow the channel."""
        channel_username = "lampinoshop"
        self.bot.send_message(
            self.chat.id,
            f"برای استفاده از ربات، لطفاً ابتدا کانال ما را دنبال کنید: [@{channel_username}]",
        )
        return
  
    def __add_to_cart(self, product_id):
        """Add a specific product to the user's cart when accessed via /start."""
        # Query the product from the database
        product = self.session.query(db.Product).filter_by(id=product_id, deleted=False).one_or_none()
        if not product:
            self.bot.send_message(self.chat.id, "❌ محصول موردنظر یافت نشد.")
            return

        # Ensure the user's cart is initialized
        if not hasattr(self, "cart"):
            self.cart = {}

        # Check if the product is already in the cart
        if product_id in self.cart:
            self.cart[product_id][1] += 1  # Increment the quantity
        else:
            # Add the product to the cart with quantity 1
            self.cart[product_id] = [product, 1]

        # Create the inline keyboard to update the cart
        product_inline_keyboard = telegram.InlineKeyboardMarkup([
            [
                telegram.InlineKeyboardButton(self.loc.get("menu_add_to_cart"), callback_data="cart_add"),
                telegram.InlineKeyboardButton(self.loc.get("menu_remove_from_cart"), callback_data="cart_remove"),
            ]
        ])

        # Send the product details with the inline keyboard
        if product.image is None:
            msg = self.bot.send_message(
                self.chat.id,
                product.text(w=self, cart_qty=self.cart[product_id][1]),
                reply_markup=product_inline_keyboard
            )
        else:
            msg = self.bot.send_photo(
                self.chat.id,
                photo=product.image,
                caption=product.text(w=self, cart_qty=self.cart[product_id][1]),
                reply_markup=product_inline_keyboard
            )

        # Create a final action keyboard
        final_inline_keyboard = telegram.InlineKeyboardMarkup([
            [telegram.InlineKeyboardButton(self.loc.get("menu_cancel"), callback_data="cart_cancel")],
            [telegram.InlineKeyboardButton(self.loc.get("menu_done"), callback_data="cart_done")]
        ])

        final_msg = self.bot.send_message(
            self.chat.id,
            self.loc.get("conversation_cart_actions"),
            reply_markup=final_inline_keyboard
        )

        # Handle user interactions
        while True:
            callback = self.__wait_for_inlinekeyboard_callback()

            # Cancel cart
            if callback.data == "cart_cancel":
                self.bot.send_message(self.chat.id, "❌ عملیات لغو شد.")
                return

            # Add product
            elif callback.data == "cart_add":
                self.cart[product_id][1] += 1
            # Remove product
            elif callback.data == "cart_remove":
                if self.cart[product_id][1] > 0:
                    self.cart[product_id][1] -= 1
                else:
                    continue
            # Finish
            elif callback.data == "cart_done":
                break

            # Update product message
            if product.image is None:
                self.bot.edit_message_text(
                    chat_id=self.chat.id,
                    message_id=msg.message_id,
                    text=product.text(w=self, cart_qty=self.cart[product_id][1]),
                    reply_markup=product_inline_keyboard
                )
            else:
                self.bot.edit_message_caption(
                    chat_id=self.chat.id,
                    message_id=msg.message_id,
                    caption=product.text(w=self, cart_qty=self.cart[product_id][1]),
                    reply_markup=product_inline_keyboard
                )

            # Update final cart summary
            self.bot.edit_message_text(
                chat_id=self.chat.id,
                message_id=final_msg.message_id,
                text=self.loc.get(
                    "conversation_confirm_cart",
                    product_list=self.__get_cart_summary(self.cart),
                    total_cost=str(self.__get_cart_value(self.cart))
                ),
                reply_markup=final_inline_keyboard
            )

        # Notify the user
        self.bot.send_message(
            self.chat.id,
            f"✅ محصول '{product.name}' به سبد خرید شما افزوده شد."
        )

        user_info = self.ask_user_info()

        # Background Color
        background_color = self.ask_background_color()

        # Neon Color
        neon_colors = self.ask_neon_color()

        # Hanger Option
        hanger_option = self.ask_hanger_option()

        # Flash and Adapter Options
        flash_and_adapter = self.ask_flash_and_adapter()

        # Delivery Options
        delivery_options = self.ask_delivery_options()


        
        
        order_summary = (
            f"👤 نام: {user_info['name']}\n"
            f"📅 کد ملی: {user_info['national_id']}\n"
            f"📞 شماره تماس: {user_info['phone']}\n"
            f"🎨 رنگ پس‌زمینه: { background_color}\n"
            f"💡 رنگ‌های نئون:\n"
            + "\n".join(
                [f"   - {label} ({hex_code})" for label, hex_code in neon_colors.values()]
            )
            + "\n"
            f"🪝 جا آویز: {hanger_option}\n"
            f"💡 فلاشر: {flash_and_adapter['flasher']}\n"
            f"🔌 آداپتور: {flash_and_adapter['adapter']}\n"
            f"🚚 روش ارسال: {delivery_options['delivery_method']}\n"
            f"📍 آدرس: {delivery_options['delivery_address']}"
        )
        

        self.bot.send_message(self.chat.id, f"📜 خلاصه سفارش:\n{order_summary}")
        self.session.commit()
            # Wait for payment
        self.bot.send_message(self.chat.id, self.loc.get("ask_payment_image"))
        payment_photo = self.__wait_for_photo(cancellable=False)

        # Process payment image and finalize the order
        photo_file = self.bot.get_file(payment_photo[0].file_id)
        self.bot.send_message(self.chat.id, self.loc.get("downloading_image"))
        self.bot.send_chat_action(self.chat.id, action="upload_photo")

        # Create the order in the database
        order_db = db.Order(
            user=self.user,
            creation_date=datetime.datetime.now(),
            notes=order_summary
        )
        order_db.set_image(photo_file)
        self.session.add(order_db)

        # Add the cart items to the order
        for product_id, (product, qty) in self.cart.items():
            for _ in range(qty):
                order_item = db.OrderItem(product=product, order=order_db)
                self.session.add(order_item)

        # Commit the session and complete the transaction
        self.session.commit()
        self.__order_transaction(order=order_db, value=-int(self.__get_cart_value(self.cart)))

        self.bot.send_message(self.chat.id, "✅ سفارش شما با موفقیت ثبت شد.")


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

        # Handle Add to Cart via /start arguments
        log.info(self.start_args)
        if self.start_args:
            if self.start_args.startswith("add_"):
                product_id = self.start_args.split("_")[1]
                self.__add_to_cart(product_id)
                return  # End the process after handling Add to Cart


        # Check if the user is following the channel
        if not self.__is_user_following_channel():
            self.__recommend_channel()
            return  # End process if user isn't following the channel
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
            # Return the first capture group if it exists; otherwise, the entire match
            return match.group(1) if match.lastindex else match.group(0)

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
        """Handle the text order process including custom text, font selection, and payment."""
        # Step 1: Ask for custom text
        self.bot.send_message(self.chat.id, "📝 لطفاً متن مورد نظر خود را برای تابلو نئون وارد کنید:")
        custom_text = self.__wait_for_regex(r"(.+)", cancellable=True)

        if isinstance(custom_text, CancelSignal):
            self.bot.send_message(self.chat.id, "❌ سفارش لغو شد.")
            return

        # Step 2: Ask for font
        font_keyboard = telegram.InlineKeyboardMarkup([
            [telegram.InlineKeyboardButton("دستنویس تک خط", callback_data="danstevis")],
            [telegram.InlineKeyboardButton("ب تیتر دو خط", callback_data="Btitr")],
            [telegram.InlineKeyboardButton("دست نویس دو خط", callback_data="danstevis_2")],
            [telegram.InlineKeyboardButton("ایران سنس", callback_data="iransans")],
        ])
        self.bot.send_message(
            self.chat.id,
            "🔤 لطفاً فونت مورد نظر خود را انتخاب کنید:",
            reply_markup=font_keyboard
        )
        font_callback = self.__wait_for_inlinekeyboard_callback()
        font_choice = font_callback.data

        # Step 3: Collect additional order details (from __collect_info)
        order_info = self.__collect_info()

        # Step 4: Generate and send PDF (or image if needed)
        self.bot.send_message(self.chat.id, "📄 در حال ساخت پیش نمایش سفارش شما...")
        
        #mamad ramzi

        print('befor generate')
        text_png_path = self.__generate_text_image( custom_text,'danstevis' if font_choice =='danstevis_2' else font_choice ,
                                                   background_color= 'white' if order_info['background_color'] == 'سفید' else 'black',
                                                   neon_colors= order_info['neon_colors'].values(), shape=order_info['board_details']['shape'],
                                                    single_line = True if font_choice in ['danstevis','iransans'] else False , border = order_info['border'] )
        
        if text_png_path:
            self.bot.send_photo(self.chat.id, open('/home/doitiir/public_html/'+text_png_path, "rb") ,caption = 'طرح نهاییتون میتونه طبق سلیقه شما باشه و این تنها یک پیش نمایش از متن شماست. ')

        # Step 5: Create the order in the database
        order = db.Order(
            user=self.user,
            creation_date=datetime.datetime.now(),
            notes=f"سفارش متن: {custom_text}",
        )
        self.session.add(order)
        self.session.commit()

        # Create a Product for the custom text order
        product = db.Product(
            name=f'{custom_text} تابلو متن دلخواه',
            description='',
            price=len(custom_text) * 150000,  # Example price logic based on text length
            deleted=False
            
        )
        
        product.set_image(file='https://doiti.ir/'+text_png_path)
        self.session.add(product)
        self.session.commit()

        # Create the order item for the custom product
        order_item = db.OrderItem(product=product, order=order)
        self.session.add(order_item)
        self.session.commit()

        # Step 6: Notify the user with the order summary
        order_summary = (
            f"👤 نام: {order_info['user_info']['name']}\n"
            f"📅 کد ملی: {order_info['user_info']['national_id']}\n"
            f"📞 شماره تماس: {order_info['user_info']['phone']}\n"
            f"📐 شکل تابلو: {order_info['board_details']['shape']}\n"
            f"📏 ابعاد: {order_info['board_details']['dimensions']}\n"
            f"🎨 رنگ پس‌زمینه: {order_info['background_color']}\n"
            f"💡 رنگ‌های نئون:\n"
            + "\n".join(
                [f"   - {label} ({hex_code})" for label, hex_code in order_info['neon_colors'].values()]
            )
            + "\n"
            f"🪝 جا آویز: {order_info['hanger']}\n"
            f"🖌️ دورگیری: {order_info['border']}\n"
            f"💡 فلاشر: {order_info['flash_and_adapter']['flasher']}\n"
            f"🔌 آداپتور: {order_info['flash_and_adapter']['adapter']}\n"
            f"🚚 روش ارسال: {order_info['delivery']['method']}\n"
            f"📍 آدرس: {order_info['delivery']['address']}\n"
            f"📝 متن سفارشی: {custom_text}\n"
        )

        # Confirm order with the user
        confirmation_keyboard = telegram.InlineKeyboardMarkup([
            [telegram.InlineKeyboardButton("تایید", callback_data="yes"),
            telegram.InlineKeyboardButton("لغو", callback_data="no")]
        ])

        self.bot.send_message(self.chat.id, f"سفارش شما:\n{order_summary}\nلطفاً تایید کنید.", reply_markup=confirmation_keyboard)

        # Wait for user confirmation
        confirmation = self.__wait_for_inlinekeyboard_callback()
        confirmation = confirmation.data

        if confirmation == "yes":
            # Redirect to payment
            self.bot.send_message(self.chat.id, self.loc.get("ask_payment_image"))
            payment_photo = self.__wait_for_photo(cancellable=False)

            # Get the payment photo
            photo_file = self.bot.get_file(payment_photo[0].file_id)
            self.bot.send_message(self.chat.id, self.loc.get("downloading_image"))
            self.bot.send_chat_action(self.chat.id, action="upload_photo")

            # Set the image for the order and commit
            order.set_image(photo_file)
            self.session.commit()

            # Final transaction for the order
            self.__order_transaction(order=order, value=-int(self.__get_cart_value(self.cart)))

        else:
            # Cancel the order
            self.bot.send_message(self.chat.id, "❌ سفارش شما لغو شد.")
    


    def __generate_text_image(self, text, font_choice, background_color, neon_colors, shape,border,single_line):
        """Send a request to the PHP server to generate the PNG file for the custom text order."""
        

        output_path =f"text_order_{uuid.uuid4().hex}.jpg"
        url = "https://doiti.ir/mmd.php"
        print(url)
        payload = json.dumps({
        "parameters": {
            "text":text,
            "font": font_choice,
            "shadowColors": [neon_color[1] for neon_color in neon_colors],
            "outputPath":  output_path,
            "shape": "border" if border == 'بله' else shape,
            "single_line": single_line,
            "background_color":background_color
        }
        })
        print(payload)
        headers = {
        'Content-Type': 'application/json'
        }

        # Send the request to the PHP server (adjust the URL based on your PHP file location)
       
        try:
            response = requests.request("POST", url, headers=headers, data=payload)
            response.raise_for_status()  # Raise an error for bad HTTP responses (4xx, 5xx)
            
            # Assuming the PHP server returns the file path to the generated PNG
            png_path = output_path
            print(response.content)
            if png_path:
                return png_path  # Return the path to the PNG file for further use
            else:
                self.bot.send_message(self.chat.id, "❌ خطا در پردازش تصویر.")
                return None
        
        except requests.exceptions.RequestException as e:
            # Handle errors that occur during the request
            self.bot.send_message(self.chat.id, f"❌ مشکلی در ارتباط با سرور پیش آمد: {e}")
            return None

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
    


    def __collect_info(self):
        # Personal Info
        user_info = self.ask_user_info()

        # Board Details
        board_details = self.ask_board_details()

        # Background Color
        background_color = self.ask_background_color()

        # Neon Color
        neon_colors = self.ask_neon_color()

        # Hanger Option
        hanger_option = self.ask_hanger_option()

        # Border Option
        border_option = self.ask_border_option()

        # Flash and Adapter Options
        flash_and_adapter = self.ask_flash_and_adapter()

        # Delivery Options
        delivery_options = self.ask_delivery_options()

        # Combine all information
        # Combine all information
        order = {
            "user_info": {
                "name": user_info["name"],
                "national_id": user_info["national_id"],  # Assuming ID was used for this field
                "phone": user_info["phone"],
            },
            "board_details": {
                "shape": board_details["shape"],
                "dimensions": f"{board_details['length']}x{board_details['width']} سانتی‌متر",
            },
            "background_color": background_color,  # Single color
            "neon_colors": neon_colors,  # Dictionary of up to 3 colors with HEX codes
            "hanger": hanger_option,  # Boolean or descriptive text
            "border": border_option,  # Boolean or descriptive text
            "flash_and_adapter": {
                "flasher": flash_and_adapter["flasher"],
                "adapter": flash_and_adapter["adapter"],
            },
            "delivery": {
                "method": delivery_options["delivery_method"],
                "address": delivery_options["delivery_address"],
            },
        }
        return order


    def __order_menu(self):
        """User menu to order products from the shop."""
        log.debug("Displaying __order_menu")
        # Get the products list from the db
        order_type = self.__order_type_selection()

        if order_type == "order_text":
            self.__text_order_process()
            return  # Exit after handling text order
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
        #summery =  self.__collect_info()
        # Personal Info
        user_info = self.ask_user_info()

        # Background Color
        background_color = self.ask_background_color()

        # Neon Color
        neon_colors = self.ask_neon_color()

        # Hanger Option
        hanger_option = self.ask_hanger_option()

        # Flash and Adapter Options
        flash_and_adapter = self.ask_flash_and_adapter()

        # Delivery Options
        delivery_options = self.ask_delivery_options()


        
        
        order_summary = (
            f"👤 نام: {user_info['name']}\n"
            f"📅 کد ملی: {user_info['national_id']}\n"
            f"📞 شماره تماس: {user_info['phone']}\n"
            f"🎨 رنگ پس‌زمینه: { background_color}\n"
            f"💡 رنگ‌های نئون:\n"
            + "\n".join(
                [f"   - {label} ({hex_code})" for label, hex_code in neon_colors.values()]
            )
            + "\n"
            f"🪝 جا آویز: {hanger_option}\n"
            f"💡 فلاشر: {flash_and_adapter['flasher']}\n"
            f"🔌 آداپتور: {flash_and_adapter['adapter']}\n"
            f"🚚 روش ارسال: {delivery_options['delivery_method']}\n"
            f"📍 آدرس: {delivery_options['delivery_address']}"
        )
        
        # Wait for user input
        notes = order_summary
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
        
    def __order_transaction(self, order, value):
        # Create a new transaction and add it to the session
        transaction = db.Transaction(user=self.user,
                                     value=value,
                                     order=order)
        self.session.add(transaction)
        # Commit all the changes
        self.session.commit()
        # Update the user's credit
        #self.user.recalculate_credit()
        # Commit all the changes
        #self.session.commit()
        # Notify admins about new transation
        self.__order_notify_admins(order=order)

    def __get_cart_value(self, cart):
        # Calculate total items value in cart
        value = self.Price(0)
        for product in cart:
            value += cart[product][0].price * cart[product][1]
        return value


    def ask_user_info(self):
        """Ask the user for personal information with error handling."""
        
        # Function to handle input validation
        def validate_input(prompt, regex, error_message):
            while True:
                self.bot.send_message(self.chat.id, prompt)
                response = self.__wait_for_regex(regex, cancellable=True)
                if isinstance(response, CancelSignal):
                    self.bot.send_message(self.chat.id, "❌ عملیات لغو شد.")
                    return None
                if response:
                    return response
                self.bot.send_message(self.chat.id, error_message)

        # Ask for user's name
        name_prompt = "👤 لطفاً نام خود را وارد کنید (حروف فارسی یا انگلیسی):"
        name_regex = r"^[\u0600-\u06FF\sA-Za-z]+$"  # Matches Persian and English letters and spaces
        name_error = "❌ نام نامعتبر است. لطفاً تنها از حروف فارسی یا انگلیسی استفاده کنید."
        name = validate_input(name_prompt, name_regex, name_error)
        if name is None:
            return None

        # Ask for national ID (Birth date field repurposed for ID)
        id_prompt = "📅 کد ملی خود را وارد کنید (۱۰ رقم):"
        id_regex = r"^\d{10}$"  # Matches exactly 10 digits
        id_error = "❌ کد ملی نامعتبر است. لطفاً ۱۰ رقم وارد کنید."
        national_id = validate_input(id_prompt, id_regex, id_error)
        if national_id is None:
            return None

        # Ask for contact information
        phone_prompt = "📞 شماره تماس خود را وارد کنید (فرمت +98 یا 09):"
        phone_regex =r"^(?:\+98|0)?9[\d\u06F0-\u06F9]{9}$" # Matches +98 or 09 followed by 9 digits
        phone_error = "❌ شماره تماس نامعتبر است. لطفاً شماره‌ای معتبر وارد کنید."
        phone = validate_input(phone_prompt, phone_regex, phone_error)
        if phone is None:
            return None

        return {"name": name, "national_id": national_id, "phone": phone}


    def ask_board_details(self):
        # Inline keyboard for shape selection
        shape_keyboard = telegram.InlineKeyboardMarkup([
            [telegram.InlineKeyboardButton("🔵 دایره", callback_data="circle")],
            [telegram.InlineKeyboardButton("🔶 لوزی", callback_data="diamond")],
            [telegram.InlineKeyboardButton("⬛ مربع", callback_data="square")],
            [telegram.InlineKeyboardButton("🔲 مستطیل", callback_data="rectangle")]
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
        """Ask the user for delivery options including method and address."""
        # Step 1: Ask for the delivery method
        delivery_keyboard = telegram.InlineKeyboardMarkup([
            [telegram.InlineKeyboardButton("🚚 پست", callback_data="delivery_postal")],
            [telegram.InlineKeyboardButton("📦 مستقیم", callback_data="delivery_direct")]
        ])
        self.bot.send_message(self.chat.id, "📦 لطفاً روش ارسال را انتخاب کنید:", reply_markup=delivery_keyboard)
        delivery_callback = self.__wait_for_inlinekeyboard_callback()

        # Map delivery method to user-friendly names
        delivery_mapping = {
            "delivery_postal": "پست",
            "delivery_direct": "مستقیم",
        }
        delivery_method = delivery_mapping.get(delivery_callback.data, "نامشخص")

        # Step 2: Ask for the delivery address
        self.bot.send_message(self.chat.id, "📍 لطفاً آدرس ارسال را وارد کنید:")
        delivery_address = self.__wait_for_regex(r".{5,}", cancellable=True)  # At least 5 characters for validation

        if isinstance(delivery_address, CancelSignal):
            self.bot.send_message(self.chat.id, "❌ عملیات لغو شد.")
            return None

        return {
            "delivery_method": delivery_method,
            "delivery_address": delivery_address
        }
    
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
        """Allow the user to select up to 3 neon colors using inline keyboards."""
        # Define neon colors with hex codes
        neon_colors = {
            "neon_red": ("🔴 قرمز", "#FF073A"),
            "neon_blue": ("🔵 آبی", "#1B03A3"),
            "neon_green": ("🟢 سبز", "#39FF14"),
            "neon_orange": ("🟠 نارنجی", "#FF6700"),
            "neon_purple": ("🟣 بنفش", "#A349A4"),
            "neon_yellow": ("🟡 زرد", "#FFFF00"),
            "neon_pink": ("🌸 صورتی", "#FF1493"),
            "neon_white": ("⚪ سفید", "#FFFFFF"),
        }

        # Track selected colors
        selected_colors = set()

        # Initial message placeholder
        msg = None

        while True:
            # Create the inline keyboard dynamically based on selection
            buttons = []
            for key, (label, _) in neon_colors.items():
                if key in selected_colors:
                    # Add ✅ to selected options
                    buttons.append(telegram.InlineKeyboardButton(f"✅ {label}", callback_data=key))
                else:
                    buttons.append(telegram.InlineKeyboardButton(label, callback_data=key))

            # Divide buttons into rows of 2
            keyboard = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
            keyboard.append([telegram.InlineKeyboardButton("✔️ تایید انتخاب", callback_data="confirm_selection")])

            # Send or edit the message with the updated keyboard
            if not msg:
                msg = self.bot.send_message(
                    self.chat.id,
                    "💡 لطفاً تا ۳ رنگ نئون انتخاب کنید (روی گزینه‌های انتخاب‌شده کلیک کنید تا از انتخاب خارج شوند):",
                    reply_markup=telegram.InlineKeyboardMarkup(keyboard)
                )
            else:
                # Only edit if the reply markup has changed
                self.bot.edit_message_reply_markup(
                    chat_id=self.chat.id,
                    message_id=msg.message_id,
                    reply_markup=telegram.InlineKeyboardMarkup(keyboard)
                )

            # Wait for user selection
            callback = self.__wait_for_inlinekeyboard_callback()

            if callback.data == "confirm_selection":
                if 1 <= len(selected_colors) <= 3:
                    # Limit the selection to 1-3 colors
                    self.bot.send_message(self.chat.id, "✅ رنگ‌های انتخاب‌شده با موفقیت ثبت شد.")
                    break
                else:
                    self.bot.send_message(self.chat.id, "❌ لطفاً بین ۱ تا ۳ رنگ انتخاب کنید.")
                    continue

            # Toggle selection
            if callback.data in selected_colors:
                selected_colors.remove(callback.data)
            else:
                if len(selected_colors) < 3:
                    selected_colors.add(callback.data)
                else:
                    self.bot.send_message(self.chat.id, "❌ حداکثر ۳ رنگ می‌توانید انتخاب کنید.")

        # Return the selected colors with their hex codes
        return {key: neon_colors[key] for key in selected_colors}



    def ask_flash_and_adapter(self):
        """Ask the user if they need a flasher and an adapter in two steps."""
        # Step 1: Ask about the flasher
        flasher_keyboard = telegram.InlineKeyboardMarkup([
            [
                telegram.InlineKeyboardButton("✅ نیاز به فلاشر دارم", callback_data="flash_yes"),
                telegram.InlineKeyboardButton("❌ نیازی به فلاشر ندارم", callback_data="flash_no"),
            ]
        ])

        self.bot.send_message(
            self.chat.id,
            "💡 آیا به فلاشر نیاز دارید؟",
            reply_markup=flasher_keyboard
        )

        # Wait for user's response about the flasher
        flasher_callback = self.__wait_for_inlinekeyboard_callback()
        flasher_choice = flasher_callback.data

        # Map flasher callback data to user-friendly names
        flasher_mapping = {
            "flash_yes": "نیاز به فلاشر دارد",
            "flash_no": "نیاز به فلاشر ندارد",
        }
        flasher_result = flasher_mapping.get(flasher_choice, "نامشخص")

        # Step 2: Ask about the adapter
        adapter_keyboard = telegram.InlineKeyboardMarkup([
            [
                telegram.InlineKeyboardButton("✅ نیاز به آداپتور دارم", callback_data="adapter_yes"),
                telegram.InlineKeyboardButton("❌ نیازی به آداپتور ندارم", callback_data="adapter_no"),
            ]
        ])

        self.bot.send_message(
            self.chat.id,
            "🔌 آیا به آداپتور نیاز دارید؟",
            reply_markup=adapter_keyboard
        )

        # Wait for user's response about the adapter
        adapter_callback = self.__wait_for_inlinekeyboard_callback()
        adapter_choice = adapter_callback.data

        # Map adapter callback data to user-friendly names
        adapter_mapping = {
            "adapter_yes": "نیاز به آداپتور دارد",
            "adapter_no": "نیاز به آداپتور ندارد",
        }
        adapter_result = adapter_mapping.get(adapter_choice, "نامشخص")

        # Return both results as a dictionary
        return {"flasher": flasher_result, "adapter": adapter_result}

    def __get_cart_summary(self, cart):
        # Create the cart summary
        product_list = ""
        for product_id in cart:
            if cart[product_id][1] > 0:
                product_list += cart[product_id][0].text(w=self,
                                                         style="short",
                                                         cart_qty=cart[product_id][1]) + "\n"
        return product_list

 

    def __order_notify_admins(self, order):
        # Notify the user of the order result
        order.send_as_message(w=self ,chat_id = self.chat.id ,user=True,)
        
        self.bot.send_message(self.chat.id,self.loc.get("success_order_created"))
        
        # Notify the admins (in Live Orders mode) of the new order
        admins = self.session.query(db.Admin).filter_by(live_mode=True).all()
        # Create the order keyboard
        order_keyboard = telegram.InlineKeyboardMarkup(
            [
                [telegram.InlineKeyboardButton(self.loc.get("menu_complete"), callback_data="order_complete")],
                [telegram.InlineKeyboardButton(self.loc.get("menu_refund"), callback_data="order_refund")]
            ])
        # Notify them of the new placed order
        for admin in admins:

            self.bot.send_photo(admin.user_id, order.payment_image, caption=self.loc.get('notification_order_placed',
                                               order=order.text(w=self)))

    def __order_status(self):
        """Display the status of the sent orders."""
        log.debug("Displaying __order_status")
        # Find the latest orders
        orders = self.session.query(db.Order) \
            .filter(db.Order.user == self.user) \
            .order_by(db.Order.creation_date.desc()) \
            .limit(20) \
            .all()
        # Ensure there is at least one order to display
        if len(orders) == 0:
            self.bot.send_message(self.chat.id, self.loc.get("error_no_orders"))
        # Display the order status to the user
        for order in orders:
            self.bot.send_message(self.chat.id, order.text(w=self, user=True))
        # TODO: maybe add a page displayer instead of showing the latest 5 orders

    def __bot_info(self):
        """Send information about the bot."""
        log.debug("Displaying __bot_info")
        self.bot.send_message(self.chat.id, self.loc.get("bot_info"))

    def __admin_menu(self):
        """Function called from the run method when the user is an administrator.
        Administrative bot actions should be placed here."""
        log.debug("Displaying __admin_menu")
        # Loop used to return to the menu after executing a command
        while True:
            # Create a keyboard with the admin main menu based on the admin permissions specified in the db
            keyboard = []
            if self.admin.edit_products:
                keyboard.append([self.loc.get("menu_products")])
            if self.admin.receive_orders:
                keyboard.append([self.loc.get("menu_orders")])
            if self.admin.is_owner:
                keyboard.append([self.loc.get("menu_edit_admins")])
            keyboard.append([self.loc.get("menu_user_mode")])
            # Send the previously created keyboard to the user (ensuring it can be clicked only 1 time)
            self.bot.send_message(self.chat.id, self.loc.get("conversation_open_admin_menu"),
                                  reply_markup=telegram.ReplyKeyboardMarkup(keyboard, one_time_keyboard=True))
            # Wait for a reply from the user
            selection = self.__wait_for_specific_message([self.loc.get("menu_products"),
                                                          self.loc.get("menu_orders"),
                                                          self.loc.get("menu_user_mode"),
                                                          self.loc.get("menu_csv"),
                                                          self.loc.get("menu_edit_admins")])
            # If the user has selected the Products option and has the privileges to perform the action...
            if selection == self.loc.get("menu_products") and self.admin.edit_products:
                # Open the products menu
                self.__products_menu()
            # If the user has selected the Orders option and has the privileges to perform the action...
            elif selection == self.loc.get("menu_orders") and self.admin.receive_orders:
                # Open the orders menu
                self.__orders_menu()
           # If the user has selected the User mode option and has the privileges to perform the action...
            elif selection == self.loc.get("menu_user_mode"):
                # Tell the user how to go back to admin menu
                self.bot.send_message(self.chat.id, self.loc.get("conversation_switch_to_user_mode"))
                # Start the bot in user mode
                self.__user_menu()
            # If the user has selected the Add Admin option and has the privileges to perform the action...
            elif selection == self.loc.get("menu_edit_admins") and self.admin.is_owner:
                # Open the edit admin menu
                self.__add_admin()
            # If the user has selected the .csv option and has the privileges to perform the action...
            elif selection == self.loc.get("menu_csv") and self.admin.create_transactions:
                # Generate the .csv file
                self.__transactions_file()

    def __products_menu(self):
        """Display the admin menu to select a product to edit."""
        log.debug("Displaying __products_menu")
        # Get the products list from the db
        products = self.session.query(db.Product).filter_by(deleted=False).all()
        # Create a list of product names
        product_names = [product.name for product in products]
        # Insert at the start of the list the add product option, the remove product option and the Cancel option
        product_names.insert(0, self.loc.get("menu_cancel"))
        product_names.insert(1, self.loc.get("menu_add_product"))
        product_names.insert(2, self.loc.get("menu_delete_product"))
        # Create a keyboard using the product names
        keyboard = [[telegram.KeyboardButton(product_name)] for product_name in product_names]
        # Send the previously created keyboard to the user (ensuring it can be clicked only 1 time)
        self.bot.send_message(self.chat.id, self.loc.get("conversation_admin_select_product"),
                              reply_markup=telegram.ReplyKeyboardMarkup(keyboard, one_time_keyboard=True))
        # Wait for a reply from the user
        selection = self.__wait_for_specific_message(product_names, cancellable=True)
        # If the user has selected the Cancel option...
        if isinstance(selection, CancelSignal):
            # Exit the menu
            return
        # If the user has selected the Add Product option...
        elif selection == self.loc.get("menu_add_product"):
            # Open the add product menu
            self.__edit_product_menu()
        # If the user has selected the Remove Product option...
        elif selection == self.loc.get("menu_delete_product"):
            # Open the delete product menu
            self.__delete_product_menu()
        # If the user has selected a product
        else:
            # Find the selected product
            product = self.session.query(db.Product).filter_by(name=selection, deleted=False).one()
            # Open the edit menu for that specific product
            self.__edit_product_menu(product=product)

    def __edit_product_menu(self, product: Optional[db.Product] = None):
        """Add a product to the database or edit an existing one."""
        log.debug("Displaying __edit_product_menu")
        # Create an inline keyboard with a single skip button
        cancel = telegram.InlineKeyboardMarkup([[telegram.InlineKeyboardButton(self.loc.get("menu_skip"),
                                                                               callback_data="cmd_cancel")]])
        # Ask for the product name until a valid product name is specified
        while True:
            # Ask the question to the user
            self.bot.send_message(self.chat.id, self.loc.get("ask_product_name"))
            # Display the current name if you're editing an existing product
            if product:
                self.bot.send_message(self.chat.id, self.loc.get("edit_current_value", value=escape(product.name)),
                                      reply_markup=cancel)
            # Wait for an answer
            name = self.__wait_for_regex(r"(.*)", cancellable=bool(product))
            # Ensure a product with that name doesn't already exist
            if (product and isinstance(name, CancelSignal)) or \
                    self.session.query(db.Product).filter_by(name=name, deleted=False).one_or_none() in [None, product]:
                # Exit the loop
                break
            self.bot.send_message(self.chat.id, self.loc.get("error_duplicate_name"))
        # Ask for the product description
        self.bot.send_message(self.chat.id, self.loc.get("ask_product_description"))
        # Display the current description if you're editing an existing product
        if product:
            self.bot.send_message(self.chat.id,
                                  self.loc.get("edit_current_value", value=escape(product.description)),
                                  reply_markup=cancel)
        # Wait for an answer
        description = self.__wait_for_regex(r"(.*)", cancellable=bool(product))
        # Ask for the product price
        self.bot.send_message(self.chat.id,
                              self.loc.get("ask_product_price"))
        # Display the current name if you're editing an existing product
        if product:
            if product.price is not None:
                value_text = str(self.Price(product.price))
            else:
                value_text = self.loc.get("text_not_for_sale")
            self.bot.send_message(
                self.chat.id,
                self.loc.get("edit_current_value", value=value_text),
                reply_markup=cancel
            )
        # Wait for an answer
        price = self.__wait_for_regex(r"([0-9]+(?:[.,][0-9]{1,2})?|[Xx])",
                                      cancellable=True)
        # If the price is skipped
        if isinstance(price, CancelSignal):
            pass
        elif price.lower() == "x":
            price = None
        else:
            price = self.Price(price)
        if not isinstance(price, CancelSignal) and price is not None:
            price = int(price)
        # Ask for the product image
        self.bot.send_message(self.chat.id, self.loc.get("ask_product_image"), reply_markup=cancel)
        # Wait for an answer
        photo_list = self.__wait_for_photo(cancellable=True)
        # If a new product is being added...
        if not product:
            # Create the db record for the product
            # noinspection PyTypeChecker
            product = db.Product(name=name,
                                 description=description,
                                 price=price,
                                 deleted=False)
            # Add the record to the database
            self.session.add(product)
        # If a product is being edited...
        else:
            # Edit the record with the new values
            product.name = name if not isinstance(name, CancelSignal) else product.name
            product.description = description if not isinstance(description, CancelSignal) else product.description
            product.price = price if not isinstance(price, CancelSignal) else product.price
        # If a photo has been sent...
        if isinstance(photo_list, list):
            # Find the largest photo id
            largest_photo = photo_list[0]
            for photo in photo_list[1:]:
                if photo.width > largest_photo.width:
                    largest_photo = photo
            # Get the file object associated with the photo
            photo_file = self.bot.get_file(largest_photo.file_id)
            # Notify the user that the bot is downloading the image and might be inactive for a while
            self.bot.send_message(self.chat.id, self.loc.get("downloading_image"))
            self.bot.send_chat_action(self.chat.id, action="upload_photo")
            # Set the image for that product
            product.set_image(photo_file)
        # Commit the session changes
        self.session.commit()
            # Create the inline keyboard for adding to cart
        channel_keyboard = telegram.InlineKeyboardMarkup([
            [
                telegram.InlineKeyboardButton(
                    text="ثبت سفارش از طریق ربات",
                    url=f"https://t.me/{self.bot.get_username(self)}?start=add_{product.id}"
                )
            ]
        ])

        # Send the product to the channel with the inline keyboard
        self.bot.send_photo(
            chat_id='-1001569827046',
            photo=product.image,
            caption=product.text(w=self),
            reply_markup=channel_keyboard
        )
                
        self.bot.send_message(self.chat.id, self.loc.get("success_product_edited"))


    def __delete_product_menu(self):
        log.debug("Displaying __delete_product_menu")
        # Get the products list from the db
        products = self.session.query(db.Product).filter_by(deleted=False).all()
        # Create a list of product names
        product_names = [product.name for product in products]
        # Insert at the start of the list the Cancel button
        product_names.insert(0, self.loc.get("menu_cancel"))
        # Create a keyboard using the product names
        keyboard = [[telegram.KeyboardButton(product_name)] for product_name in product_names]
        # Send the previously created keyboard to the user (ensuring it can be clicked only 1 time)
        self.bot.send_message(self.chat.id, self.loc.get("conversation_admin_select_product_to_delete"),
                              reply_markup=telegram.ReplyKeyboardMarkup(keyboard, one_time_keyboard=True))
        # Wait for a reply from the user
        selection = self.__wait_for_specific_message(product_names, cancellable=True)
        if isinstance(selection, CancelSignal):
            # Exit the menu
            return
        else:
            # Find the selected product
            product = self.session.query(db.Product).filter_by(name=selection, deleted=False).one()
            # "Delete" the product by setting the deleted flag to true
            product.deleted = True
            self.session.commit()
            # Notify the user
            self.bot.send_message(self.chat.id, self.loc.get("success_product_deleted"))

    def __orders_menu(self):
        """Display a live flow of orders."""
        log.debug("Displaying __orders_menu")
        # Create a cancel and a stop keyboard
        stop_keyboard = telegram.InlineKeyboardMarkup([[telegram.InlineKeyboardButton(self.loc.get("menu_stop"),
                                                                                      callback_data="cmd_cancel")]])
        cancel_keyboard = telegram.InlineKeyboardMarkup([[telegram.InlineKeyboardButton(self.loc.get("menu_cancel"),
                                                                                        callback_data="cmd_cancel")]])
        # Send a small intro message on the Live Orders mode
        # Remove the keyboard with the first message... (#39)
        self.bot.send_message(self.chat.id,
                              self.loc.get("conversation_live_orders_start"),
                              reply_markup=telegram.ReplyKeyboardRemove())
        # ...and display a small inline keyboard with the following one
        self.bot.send_message(self.chat.id,
                              self.loc.get("conversation_live_orders_stop"),
                              reply_markup=stop_keyboard)
        # Create the order keyboard
        order_keyboard = telegram.InlineKeyboardMarkup([[telegram.InlineKeyboardButton(self.loc.get("menu_complete"),
                                                                                       callback_data="order_complete")],
                                                        [telegram.InlineKeyboardButton(self.loc.get("menu_refund"),
                                                                                       callback_data="order_refund")]])
        # Display the past pending orders
        orders = self.session.query(db.Order) \
            .filter_by(delivery_date=None, refund_date=None) \
            .join(db.Transaction) \
            .join(db.User) \
            .all()
        # Create a message for every one of them
        for order in orders:
            # Send the created message
            self.bot.send_message(self.chat.id, order.text(w=self),
                                  reply_markup=order_keyboard)
        # Set the Live mode flag to True
        self.admin.live_mode = True
        # Commit the change to the database
        self.session.commit()
        while True:
            # Wait for any message to stop the listening mode
            update = self.__wait_for_inlinekeyboard_callback(cancellable=True)
            # If the user pressed the stop button, exit listening mode
            if isinstance(update, CancelSignal):
                # Stop the listening mode
                self.admin.live_mode = False
                break
            # Find the order
            order_id = re.search(self.loc.get("order_number").replace("{id}", "([0-9]+)"), update.message.text).group(1)
            order = self.session.query(db.Order).get(order_id)
            # Check if the order hasn't been already cleared
            if order.delivery_date is not None or order.refund_date is not None:
                # Notify the admin and skip that order
                self.bot.edit_message_text(self.chat.id, self.loc.get("error_order_already_cleared"))
                break
            # If the user pressed the complete order button, complete the order
            #if update.data == "order_complete":
                # Mark the order as complete
            order.delivery_date = datetime.datetime.now()
            # Commit the transaction
            self.session.commit()
            # Update order message
            self.bot.edit_message_text(order.text(w=self), chat_id=self.chat.id,
                                        message_id=update.message.message_id)
            # Notify the user of the completition
            self.bot.send_message(order.user_id,
                                    self.loc.get("notification_order_completed",
                                                order=order.text(w=self, user=True)))
            # If the user pressed the refund order button, refund the order...
            # elif update.data == "order_refund":
            #     # Ask for a refund reason
            #     reason_msg = self.bot.send_message(self.chat.id, self.loc.get("ask_refund_reason"),
            #                                        reply_markup=cancel_keyboard)
            #     # Wait for a reply
            #     reply = self.__wait_for_regex("(.*)", cancellable=True)
            #     # If the user pressed the cancel button, cancel the refund
            #     if isinstance(reply, CancelSignal):
            #         # Delete the message asking for the refund reason
            #         self.bot.delete_message(self.chat.id, reason_msg.message_id)
            #         continue
            #     # Mark the order as refunded
            #     order.refund_date = datetime.datetime.now()
            #     # Save the refund reason
            #     order.refund_reason = reply
            #     # Refund the credit, reverting the old transaction
            #     order.transaction.refunded = True
            #     # Update the user's credit
            #     order.user.recalculate_credit()
            #     # Commit the changes
            #     self.session.commit()
            #     # Update the order message
            #     self.bot.edit_message_text(order.text(w=self),
            #                                chat_id=self.chat.id,
            #                                message_id=update.message.message_id)
            #     # Notify the user of the refund
            #     self.bot.send_message(order.user_id,
            #                           self.loc.get("notification_order_refunded", order=order.text(w=self,
            #                                                                                        user=True)))
            #     # Notify the admin of the refund
            #     self.bot.send_message(self.chat.id, self.loc.get("success_order_refunded", order_id=order.order_id))

   
    def __help_menu(self):
        """Help menu. Allows the user to ask for assistance, get a guide or see some info about the bot."""
        log.debug("Displaying __help_menu")
        # Create a keyboard with the user help menu
        keyboard = [[telegram.KeyboardButton(self.loc.get("menu_guide"))],
                    [telegram.KeyboardButton(self.loc.get("menu_contact_shopkeeper"))],
                    [telegram.KeyboardButton(self.loc.get("menu_cancel"))]]
        # Send the previously created keyboard to the user (ensuring it can be clicked only 1 time)
        self.bot.send_message(self.chat.id,
                              self.loc.get("conversation_open_help_menu"),
                              reply_markup=telegram.ReplyKeyboardMarkup(keyboard, one_time_keyboard=True))
        # Wait for a reply from the user
        selection = self.__wait_for_specific_message([
            self.loc.get("menu_guide"),
            self.loc.get("menu_contact_shopkeeper")
        ], cancellable=True)
        # If the user has selected the Guide option...
        if selection == self.loc.get("menu_guide"):
            # Send them the bot guide
            self.bot.send_message(self.chat.id, self.loc.get("help_msg"))
        # If the user has selected the Order Status option...
        elif selection == self.loc.get("menu_contact_shopkeeper"):
            # Find the list of available shopkeepers
            shopkeepers = self.session.query(db.Admin).filter_by(display_on_help=True).join(db.User).all()
            # Create the string
            shopkeepers_string = "\n".join([admin.user.mention() for admin in shopkeepers])
            # Send the message to the user
            self.bot.send_message(self.chat.id, self.loc.get("contact_shopkeeper", shopkeepers=shopkeepers_string))
        # If the user has selected the Cancel option the function will return immediately


    def __transactions_file(self):
        """Generate a .csv file containing the list of all transactions."""
        log.debug("Generating __transaction_file")
        # Retrieve all the transactions
        transactions = self.session.query(db.Transaction).order_by(db.Transaction.transaction_id).all()
        # Write on the previously created file
        with open(f"transactions_{self.chat.id}.csv", "w") as file:
            # Write an header line
            file.write(f"UserID;"
                       f"TransactionValue;"
                       f"TransactionNotes;"
                       f"Provider;"
                       f"ChargeID;"
                       f"SpecifiedName;"
                       f"SpecifiedPhone;"
                       f"SpecifiedEmail;"
                       f"Refunded?\n")
            # For each transaction; write a new line on file
            for transaction in transactions:
                file.write(f"{transaction.user_id if transaction.user_id is not None else ''};"
                           f"{transaction.value if transaction.value is not None else ''};"
                           f"{transaction.notes if transaction.notes is not None else ''};"
                           f"{transaction.provider if transaction.provider is not None else ''};"
                           f"{transaction.provider_charge_id if transaction.provider_charge_id is not None else ''};"
                           f"{transaction.payment_name if transaction.payment_name is not None else ''};"
                           f"{transaction.payment_phone if transaction.payment_phone is not None else ''};"
                           f"{transaction.payment_email if transaction.payment_email is not None else ''};"
                           f"{transaction.refunded if transaction.refunded is not None else ''}\n")
        # Describe the file to the user
        self.bot.send_message(self.chat.id, self.loc.get("csv_caption"))
        # Reopen the file for reading
        with open(f"transactions_{self.chat.id}.csv") as file:
            # Send the file via a manual request to Telegram
            requests.post(f"https://api.telegram.org/bot{self.cfg['Telegram']['token']}/sendDocument",
                          files={"document": file},
                          params={"chat_id": self.chat.id,
                                  "parse_mode": "HTML"})
        # Delete the created file
        os.remove(f"transactions_{self.chat.id}.csv")

    def __add_admin(self):
        """Add an administrator to the bot."""
        log.debug("Displaying __add_admin")
        # Let the admin select an administrator to promote
        user = self.__user_select()
        # Allow the cancellation of the operation
        if isinstance(user, CancelSignal):
            return
        # Check if the user is already an administrator
        admin = self.session.query(db.Admin).filter_by(user=user).one_or_none()
        if admin is None:
            # Create the keyboard to be sent
            keyboard = telegram.ReplyKeyboardMarkup([[self.loc.get("emoji_yes"), self.loc.get("emoji_no")]],
                                                    one_time_keyboard=True)
            # Ask for confirmation
            self.bot.send_message(self.chat.id, self.loc.get("conversation_confirm_admin_promotion"),
                                  reply_markup=keyboard)
            # Wait for an answer
            selection = self.__wait_for_specific_message([self.loc.get("emoji_yes"), self.loc.get("emoji_no")])
            # Proceed only if the answer is yes
            if selection == self.loc.get("emoji_no"):
                return
            # Create a new admin
            admin = db.Admin(user=user,
                             edit_products=False,
                             receive_orders=False,
                             create_transactions=False,
                             is_owner=False,
                             display_on_help=False)
            self.session.add(admin)
        # Send the empty admin message and record the id
        message = self.bot.send_message(self.chat.id, self.loc.get("admin_properties", name=str(admin.user)))
        # Start accepting edits
        while True:
            # Create the inline keyboard with the admin status
            inline_keyboard = telegram.InlineKeyboardMarkup([
                [telegram.InlineKeyboardButton(
                    f"{self.loc.boolmoji(admin.edit_products)} {self.loc.get('prop_edit_products')}",
                    callback_data="toggle_edit_products"
                )],
                [telegram.InlineKeyboardButton(
                    f"{self.loc.boolmoji(admin.receive_orders)} {self.loc.get('prop_receive_orders')}",
                    callback_data="toggle_receive_orders"
                )],
                [telegram.InlineKeyboardButton(
                    f"{self.loc.boolmoji(admin.create_transactions)} {self.loc.get('prop_create_transactions')}",
                    callback_data="toggle_create_transactions"
                )],
                [telegram.InlineKeyboardButton(
                    f"{self.loc.boolmoji(admin.display_on_help)} {self.loc.get('prop_display_on_help')}",
                    callback_data="toggle_display_on_help"
                )],
                [telegram.InlineKeyboardButton(
                    self.loc.get('menu_done'),
                    callback_data="cmd_done"
                )]
            ])
            # Update the inline keyboard
            self.bot.edit_message_reply_markup(message_id=message.message_id,
                                               chat_id=self.chat.id,
                                               reply_markup=inline_keyboard)
            # Wait for an user answer
            callback = self.__wait_for_inlinekeyboard_callback()
            # Toggle the correct property
            if callback.data == "toggle_edit_products":
                admin.edit_products = not admin.edit_products
            elif callback.data == "toggle_receive_orders":
                admin.receive_orders = not admin.receive_orders
            elif callback.data == "toggle_create_transactions":
                admin.create_transactions = not admin.create_transactions
            elif callback.data == "toggle_display_on_help":
                admin.display_on_help = not admin.display_on_help
            elif callback.data == "cmd_done":
                break
        self.session.commit()

   
    def __create_localization(self):
        # Check if the user's language is enabled; if it isn't, change it to the default
        if self.user.language not in self.cfg["Language"]["enabled_languages"]:
            log.debug(f"User's language '{self.user.language}' is not enabled, changing it to the default")
            self.user.language = self.cfg["Language"]["default_language"]
            self.session.commit()
        # Create a new Localization object
        self.loc = localization.Localization(
            language=self.user.language,
            fallback=self.cfg["Language"]["fallback_language"],
            replacements={
                "user_string": str(self.user),
                "user_mention": self.user.mention(),
                "user_full_name": self.user.full_name,
                "user_first_name": self.user.first_name,
                "today": datetime.datetime.now().strftime("%a %d %b %Y"),
            }
        )

    def __graceful_stop(self, stop_trigger: StopSignal):
        """Handle the graceful stop of the thread."""
        log.debug("Gracefully stopping the conversation")
        # If the session has expired...
        if stop_trigger.reason == "timeout":
            # Notify the user that the session has expired and remove the keyboard
            self.bot.send_message(self.chat.id, self.loc.get('conversation_expired'),
                                  reply_markup=telegram.ReplyKeyboardRemove())
        # If a restart has been requested...
        # Do nothing.
        # Close the database session
        self.session.close()
        # End the process
        sys.exit(0)





