# رشته‌ها / فایل محلی‌سازی برای greed
# قابل ویرایش است، اما فیلدهای جایگزینی (کلماتی که داخل {آکولاد} قرار دارند) را حذف نکنید

# نماد ارز
currency_symbol = "€"

# نحوه نمایش نماد ارز
currency_format_string = "{symbol} {value}"

# مقدار موجودی یک محصول
in_stock_format_string = "{quantity} موجود است"

# تعداد نسخه‌های یک محصول در سبد خرید
in_cart_format_string = "{quantity} در سبد خرید"

# اطلاعات محصول
product_format_string = "<b>{name}</b>\n" \
                        "{description}\n" \
                        "{price}\n" \
                        "<b>{cart}</b>"

# شماره سفارش، نمایش داده شده در اطلاعات سفارش
order_number = "سفارش #{id}"

# رشته اطلاعات سفارش، نمایش داده شده به مدیران
order_format_string = "توسط {user}\n" \
                      "ایجاد شده در {date}\n" \
                      "\n" \
                      "{items}\n" \
                      "مجموع: <b>{value}</b>\n" \
                      "\n" \
                      "یادداشت‌های مشتری: {notes}\n"

# رشته اطلاعات سفارش، نمایش داده شده به کاربر
user_order_format_string = "{status_emoji} <b>سفارش {status_text}</b>\n" \
                           "{items}\n" \
                           "مجموع: <b>{value}</b>\n" \
                           "\n" \
                           "یادداشت‌ها: {notes}\n"

# صفحه تراکنش در حال بارگذاری است
loading_transactions = "<i>در حال بارگذاری تراکنش‌ها...\n" \
                       "لطفاً چند ثانیه صبر کنید.</i>"

# صفحه تراکنش‌ها
transactions_page = "صفحه <b>{page}</b>:\n" \
                    "\n" \
                    "{transactions}"

# عنوان transactions.csv
csv_caption = "📄 یک فایل .csv شامل تمام تراکنش‌های ذخیره شده در پایگاه داده بات تولید شده است.\n" \
              "می‌توانید این فایل را با برنامه‌های دیگر مانند LibreOffice Calc باز کنید تا داده‌ها را پردازش کنید."

# مکالمه: دستور شروع ارسال شده و بات باید کاربر را خوشامد بگوید
conversation_after_start = "سلام!\n" \
                           "به greed خوش آمدید!\n" \
                           "این نسخه 🅱️ <b>بتا</b> نرم‌افزار است.\n" \
                           "کاملاً قابل استفاده است، اما ممکن است هنوز برخی از باگ‌ها وجود داشته باشد.\n" \
                           "اگر باگی پیدا کردید، لطفاً آن را در https://github.com/Steffo99/greed/issues گزارش کنید."

# مکالمه: برای ارسال یک کیبورد داخلی، باید یک پیام همراه با آن ارسال کنید
conversation_open_user_menu = "دوست دارید چه کاری انجام دهید؟\n" \
                              "💰 شما <b>{credit}</b> در کیف پول خود دارید.\n" \
                              "\n" \
                              "<i>برای انتخاب یک عملیات، کلیدی را در کیبورد پایین فشار دهید.\n" \
                              "اگر کیبورد باز نشده است، می‌توانید با فشار دادن دکمه‌ای که چهار مربع کوچک در نوار پیام دارد، آن را باز کنید.</i>"

# مکالمه: مانند بالا، اما برای مدیران
conversation_open_admin_menu = "شما یک 💼 <b>مدیر</b> این فروشگاه هستید!\n" \
                               "دوست دارید چه کاری انجام دهید؟\n" \
                               "\n" \
                               "<i>برای انتخاب یک عملیات، کلیدی را در کیبورد پایین فشار دهید.\n" \
                               "اگر کیبورد باز نشده است، می‌توانید با فشار دادن دکمه‌ای که چهار مربع کوچک در نوار پیام دارد، آن را باز کنید.</i>"

# مکالمه: انتخاب روش پرداخت
conversation_payment_method = "چگونه می‌خواهید به کیف پول خود پول اضافه کنید؟"

# مکالمه: انتخاب محصول برای ویرایش
conversation_admin_select_product = "✏️ کدام محصول را می‌خواهید ویرایش کنید؟"

# مکالمه: انتخاب محصول برای حذف
conversation_admin_select_product_to_delete = "❌ کدام محصول را می‌خواهید حذف کنید؟"

# مکالمه: انتخاب یک کاربر برای ویرایش
conversation_admin_select_user = "یک کاربر را برای ویرایش انتخاب کنید."

# مکالمه: برای پرداخت هزینه خرید، دکمه زیر را کلیک کنید
conversation_cart_actions = "<i>محصولات را با پیمایش به بالا و فشردن دکمه افزودن در زیر محصولاتی که می‌خواهید به سبد اضافه کنید، اضافه کنید." \
                            " وقتی کارتان تمام شد، به این پیام بازگردید و دکمه انجام شد را در زیر فشار دهید.</i>"

# مکالمه: تأیید محتویات سبد خرید
conversation_confirm_cart = "🛒 سبد خرید شما شامل محصولات زیر است:\n" \
                            "{product_list}" \
                            "مجموع: <b>{total_cost}</b>\n" \
                            "\n" \
                            "<i>اگر می‌خواهید ادامه دهید، دکمه انجام شد را در زیر این پیام فشار دهید.\n" \
                            "برای لغو، دکمه لغو را فشار دهید.</i>"

# حالت سفارش‌های زنده: شروع
conversation_live_orders_start = "شما در حالت <b>سفارش‌های زنده</b> هستید\n" \
                                 "تمام سفارش‌های جدیدی که توسط مشتریان ثبت می‌شود به صورت زنده در این چت ظاهر می‌شوند و شما" \
                                 " می‌توانید آن‌ها را به عنوان ✅ تکمیل شده علامت بزنید" \
                                 " یا ✴️ اعتبار را به مشتری بازپرداخت کنید."

# حالت سفارش‌های زنده: توقف دریافت پیام‌ها
conversation_live_orders_stop = "<i>برای متوقف کردن فید، دکمه توقف در زیر این پیام را فشار دهید.</i>"

# مکالمه: منوی راهنما باز شده است
conversation_open_help_menu = "چه نوع کمکی نیاز دارید؟"

# مکالمه: تأیید ارتقا به مدیر
conversation_confirm_admin_promotion = "آیا مطمئن هستید که می‌خواهید این کاربر را به 💼 مدیر ارتقا دهید؟\n" \
                                       "این یک عمل غیرقابل بازگشت است!"

# مکالمه: سربرگ منوی انتخاب زبان
conversation_language_select = "یک زبان را انتخاب کنید:"

# مکالمه: تغییر به حالت کاربری
conversation_switch_to_user_mode = "شما در حال تغییر به حالت 👤 مشتری هستید.\n" \
                                   "اگر می‌خواهید به منوی 💼 مدیر بازگردید، مکالمه را با /start مجدداً شروع کنید."

# اعلان: مکالمه منقضی شده است
conversation_expired = "🕐 مدتی است که پیامی دریافت نکرده‌ام، بنابراین برای صرفه‌جویی در منابع، مکالمه را بستم.\n" \
                       "اگر می‌خواهید یک مکالمه جدید را شروع کنید، دستور /start جدید ارسال کنید."

# منوی کاربر: سفارش
menu_order = "🛒 سفارش محصولات"


# منوی کاربر: وضعیت سفارش
menu_order_status = "🛍 سفارش‌های من"

# منوی کاربر: افزودن اعتبار
menu_add_credit = "💵 افزودن وجه"

# منوی کاربر: اطلاعات بات
menu_bot_info = "ℹ️ اطلاعات بات"

# منوی کاربر: پرداخت نقدی
menu_cash = "💵 با پول نقد"

# منوی کاربر: کارت اعتباری
menu_credit_card = "💳 با کارت اعتباری"

# منوی مدیر: محصولات
menu_products = "📝️ محصولات"

# منوی مدیر: سفارش‌ها
menu_orders = "📦 سفارش‌ها"

# منو: تراکنش‌ها
menu_transactions = "💳 لیست تراکنش‌ها"

# منو: ویرایش اعتبار
menu_edit_credit = "💰 ایجاد تراکنش"

# منوی مدیر: تغییر به حالت کاربری
menu_user_mode = "👤 تغییر به حالت مشتری"

# منوی مدیر: افزودن محصول
menu_add_product = "✨ محصول جدید"

# منوی مدیر: حذف محصول
menu_delete_product = "❌ حذف محصول"

# منو: لغو
menu_cancel = "🔙 لغو"

# منو: رد کردن
menu_skip = "⏭ رد کردن"

# منو: انجام شد
menu_done = "✅️ انجام شد"

# منو: پرداخت صورتحساب
menu_pay = "💳 پرداخت"

# منو: تکمیل
menu_complete = "✅ تکمیل"

# منو: بازپرداخت
menu_refund = "✴️ بازپرداخت"

# منو: توقف
menu_stop = "🛑 توقف"

# منو: افزودن به سبد خرید
menu_add_to_cart = "➕ افزودن"

# منو: حذف از سبد خرید
menu_remove_from_cart = "➖ حذف"

# منو: منوی راهنما
menu_help = "❓ کمک / پشتیبانی"

# منو: راهنما
menu_guide = "📖 راهنما"

# منو: صفحه بعدی
menu_next = "▶️ بعدی"

# منو: صفحه قبلی
menu_previous = "◀️ قبلی"

# منو: تماس با فروشنده
menu_contact_shopkeeper = "👨‍💼 تماس با فروشگاه"

# منو: تولید فایل .csv تراکنش‌ها
menu_csv = "📄 .csv"

# منو: ویرایش لیست مدیران
menu_edit_admins = "🏵 ویرایش مدیران"

# منو: زبان
menu_language = "🇬🇧 زبان"

# ایموجی: سفارش پردازش نشده
emoji_not_processed = "*️⃣"

# ایموجی: سفارش تکمیل شده
emoji_completed = "✅"

# ایموجی: سفارش بازپرداخت شده
emoji_refunded = "✴️"

# ایموجی: بله
emoji_yes = "✅"

# ایموجی: خیر
emoji_no = "🚫"

# متن: سفارش پردازش نشده
text_not_processed = "در انتظار"

# متن: سفارش تکمیل شده
text_completed = "تکمیل شده"

# متن: سفارش بازپرداخت شده
text_refunded = "بازپرداخت شده"

# متن: محصول برای فروش نیست
text_not_for_sale = "برای فروش نیست"

# افزودن محصول: نام محصول؟
ask_product_name = "نام محصول چه باشد؟"

# افزودن محصول: توضیحات محصول؟
ask_product_description = "توضیحات محصول چه باشد؟"

# افزودن محصول: قیمت محصول؟
ask_product_price = "قیمت محصول چقدر باشد؟\n" \
                    "اگر نمی‌خواهید محصول هنوز برای فروش باشد، <code>X</code> را وارد کنید."

# افزودن محصول: تصویر محصول؟
ask_product_image = "🖼 چه تصویری را برای محصول می‌خواهید؟\n" \
                    "\n" \
                    "<i>عکس را ارسال کنید، یا این مرحله را رد کنید و هیچ تصویری اضافه نکنید.</i>"

# سفارش محصول: یادداشتی می‌خواهید بگذارید؟
ask_order_notes = "آیا می‌خواهید همراه با سفارش یک یادداشت بگذارید؟\n" \
                  "💼 این یادداشت برای مدیران فروشگاه قابل مشاهده خواهد بود.\n" \
                  "\n" \
                  "<i>پیامی با یادداشتی که می‌خواهید بگذارید ارسال کنید، یا برای گذاشتن هیچ‌چیز، دکمه رد کردن را در زیر این پیام فشار دهید.</i>"

# بازپرداخت محصول: دلیل بازپرداخت؟
ask_refund_reason = " دلیلی برای این بازپرداخت ضمیمه کنید.\n" \
                    "👤 این دلیل برای مشتری قابل مشاهده خواهد بود."

# ویرایش اعتبار: یادداشتی می‌خواهید ضمیمه کنید؟
ask_transaction_notes = "یادداشتی را به این تراکنش ضمیمه کنید.\n" \
                        "👤 این یادداشت پس از اعتباردهی / بدهکاری برای مشتری و برای 💼 مدیران در گزارش تراکنش‌ها قابل مشاهده خواهد بود."

# ویرایش اعتبار: مقدار؟
ask_credit = "چگونه می‌خواهید اعتبار مشتری را تغییر دهید؟\n" \
             "\n" \
             "<i>پیامی حاوی مقدار ارسال کنید.\n" \
             "از علامت </i><code>+</code><i> برای افزودن اعتبار به حساب مشتری استفاده کنید،" \
             " و از علامت </i><code>-</code><i> برای کسر آن.</i>"

# سربرگ پیام ویرایش مدیر
admin_properties = "<b>مجوزهای {name}:</b>"

# ویرایش مدیر: آیا می‌تواند محصولات را ویرایش کند؟
prop_edit_products = "ویرایش محصولات"

# ویرایش مدیر: آیا می‌تواند سفارش‌ها را دریافت کند؟
prop_receive_orders = "دریافت سفارش‌ها"

# ویرایش مدیر: آیا می‌تواند تراکنش‌ها ایجاد کند؟
prop_create_transactions = "مدیریت تراکنش‌ها"

# ویرایش مدیر: آیا در پیام راهنما نمایش داده شود؟
prop_display_on_help = "نمایش برای مشتری"

# موضوع شروع به دانلود تصویر کرده و ممکن است پاسخگو نباشد
downloading_image = "در حال دانلود عکس شما هستم!\n" \
                    "ممکن است کمی طول بکشد... لطفاً صبور باشید!\n" \
                    "تا زمانی که در حال دانلود هستم، نمی‌توانم پاسخگو باشم."

# ویرایش محصول: مقدار فعلی
edit_current_value = "مقدار فعلی:\n" \
                     "<pre>{value}</pre>\n" \
                     "\n" \
                     "<i>برای حفظ مقدار فعلی، دکمه رد کردن را در زیر این پیام فشار دهید.</i>"

# پرداخت: اطلاعات پرداخت نقدی
payment_cash = "می‌توانید به صورت نقدی در محل فیزیکی فروشگاه پرداخت کنید.\n" \
               "در زمان پرداخت، این شناسه را به مدیر ارائه دهید:\n" \
               "<b>{user_cash_id}</b>"

# پرداخت: مقدار صورتحساب
payment_cc_amount = "چقدر وجه می‌خواهید به کیف پول خود اضافه کنید؟\n" \
                    "\n" \
                    "<i>با دکمه‌های زیر یک مقدار را انتخاب کنید، یا آن را به صورت دستی با کیبورد عادی وارد کنید</i>"

# پرداخت: عنوان صورتحساب افزودن وجه
payment_invoice_title = "افزودن وجه"

# پرداخت: توضیحات صورتحساب افزودن وجه
payment_invoice_description = "پرداخت این صورتحساب {amount} به کیف پول شما اضافه می‌کند."

# پرداخت: برچسب قیمت مشخص در صورتحساب
payment_invoice_label = "شارژ مجدد"

# پرداخت: برچسب هزینه تراکنش در صورتحساب
payment_invoice_fee_label = "هزینه تراکنش"

# اعلان: سفارش ثبت شده است
notification_order_placed = "یک سفارش جدید ثبت شده است:\n" \
                            "\n" \
                            "{order}"

# اعلان: سفارش تکمیل شده است
notification_order_completed = "سفارش شما تکمیل شده است!\n" \
                               "\n" \
                               "{order}"

# اعلان: سفارش بازپرداخت شده است
notification_order_refunded = "سفارش شما بازپرداخت شده است!\n" \
                              "\n" \
                              "{order}"

# اعلان: یک تراکنش دستی اعمال شده است
notification_transaction_created = "ℹ️  یک تراکنش جدید به کیف پول شما اعمال شده است:\n" \
                                   "{transaction}"

# دلیل بازپرداخت
refund_reason = "دلیل بازپرداخت:\n" \
                "{reason}"

# اطلاعات: اطلاعات مربوط به بات
bot_info = 'این بات از <a href="https://github.com/Steffo99/greed">greed</a> استفاده می‌کند،' \
           ' چارچوبی توسط @Steffo برای پرداخت‌های تلگرام که تحت' \
           ' <a href="https://github.com/Steffo99/greed/blob/master/LICENSE.txt">' \
           'مجوز عمومی Affero نسخه 3.0</a> منتشر شده است.\n'

# راهنما: راهنما
help_msg = "راهنمای greed در این آدرس موجود است:\n" \
           "https://github.com/Steffo99/greed/wiki"

# راهنما: تماس با فروشنده
contact_shopkeeper = "در حال حاضر، کارکنانی که برای ارائه کمک به کاربران در دسترس هستند عبارتند از:\n" \
                     "{shopkeepers}\n" \
                     "<i>روی نام یکی از آنها کلیک کنید / ضربه بزنید تا در چت تلگرام با آنها تماس بگیرید.</i>"

# موفقیت: محصول با موفقیت به پایگاه داده اضافه/ویرایش شده است
success_product_edited = "✅ محصول با موفقیت اضافه/ویرایش شد!"

# موفقیت: محصول با موفقیت از پایگاه داده حذف شده است
success_product_deleted = "✅ محصول با موفقیت حذف شد!"

# موفقیت: سفارش با موفقیت ایجاد شد
success_order_created = "✅ سفارش با موفقیت ارسال شد!\n" \
                        "\n" \
                        "{order}"

# موفقیت: سفارش به عنوان تکمیل شده علامت‌گذاری شد
success_order_completed = "✅ شما سفارش شماره #{order_id} را به عنوان تکمیل شده علامت زدید."

# موفقیت: سفارش با موفقیت بازپرداخت شد
success_order_refunded = "✴️ سفارش شماره #{order_id} بازپرداخت شد."

# موفقیت: تراکنش با موفقیت ایجاد شد
success_transaction_created = "✅ تراکنش با موفقیت ایجاد شد!\n" \
                              "{transaction}"

# خطا: پیام دریافت شده در چت خصوصی نیست
error_nonprivate_chat = "⚠️ این بات تنها در چت‌های خصوصی کار می‌کند."

# خطا: پیامی در چت ارسال شد، اما هیچ کارگری برای آن چت وجود ندارد.
# پیشنهاد ایجاد کارگر جدید با /start
error_no_worker_for_chat = "⚠️ مکالمه با بات متوقف شد.\n" \
                           "برای راه‌اندازی مجدد، دستور /start را به بات ارسال کنید."

# خطا: پیامی در چت ارسال شد، اما کارگر برای آن چت آماده نیست.
error_worker_not_ready = "🕒 مکالمه با بات در حال راه‌اندازی است.\n" \
                         "لطفاً چند لحظه صبر کنید قبل از ارسال دستورات بیشتر!"

# خطا: مقدار افزودن اعتبار بیش از حداکثر است
error_payment_amount_over_max = "⚠️ حداکثر مقداری که می‌توان در یک تراکنش اضافه کرد {max_amount} است."

# خطا: مقدار افزودن اعتبار کمتر از حداقل است
error_payment_amount_under_min = "⚠️ حداقل مقداری که می‌توان در یک تراکنش اضافه کرد {min_amount} است."

# خطا: صورتحساب منقضی شده و قابل پرداخت نیست
error_invoice_expired = "⚠️ این صورتحساب منقضی شده و لغو شده است. اگر هنوز می‌خواهید وجه اضافه کنید، از گزینه افزودن وجه در منوی مربوطه استفاده کنید."

# خطا: محصولی با همین نام قبلاً وجود دارد
error_duplicate_name = "⚠️ محصولی با همین نام قبلاً وجود دارد."

# خطا: اعتبار کافی برای سفارش دادن ندارید
error_not_enough_credit = "⚠️ شما اعتبار کافی برای ثبت سفارش ندارید."

# خطا: سفارش قبلاً پاک شده است
error_order_already_cleared = "⚠️ این سفارش قبلاً پردازش شده است."

# خطا: هیچ سفارشی ثبت نشده است، بنابراین چیزی برای نمایش وجود ندارد
error_no_orders = "⚠️ هنوز سفارشی ثبت نکرده‌اید، بنابراین چیزی برای نمایش وجود ندارد."

# خطا: کاربر انتخاب شده وجود ندارد
error_user_does_not_exist = "⚠️ کاربر انتخاب شده وجود ندارد."

# خطای جدی: مکالمه یک استثنا رخ داده است
fatal_conversation_exception = "☢️ اوه نه! یک <b>خطا</b> مکالمه را متوقف کرد\n" \
                               "این خطا به مالک بات گزارش شد تا بتواند آن را برطرف کند.\n" \
                               "برای راه‌اندازی مجدد مکالمه، دستور /start را مجدداً ارسال کنید."
