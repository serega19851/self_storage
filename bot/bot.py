from environs import Env
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ParseMode, MessageEntity
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackQueryHandler,
    CallbackContext,
    Filters,
    MessageHandler,
    ConversationHandler,
)

import os, sys
from datetime import datetime, timedelta
import django
DJANGO_PROJECT_PATH = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.append(DJANGO_PROJECT_PATH)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "self_storage.settings")
django.setup()

from django.template.loader import render_to_string
from storage.models import User, Box, Promocodes, TransferRequest


STATIC_PAGES = (
    'forbidden_cargo',
    'faq',
    'prices',
)

WEIGHT_RANGE = {
    'до 10кг': 10,
    'от 10 до 25кг': 25,
    'от 25 до 40кг': 40,
    'от 40 до 70кг': 70,
    'от 70 до 100кг': 100,
    'больше 100кг': 200,
    'Я не знаю :(': 0,
}

VOLUME_RANGE = {
    'до 0.1м³': 0.1,
    'от 0.1 до 0.5м³': 0.5,
    'от 0.5 до 1м³': 1,
    'от 1 до 2м³': 2,
    'от 2 до 4м³': 4,
    'больше 4 м³': 8,
    'Я не знаю :(': 0,
}

STORAGE_INFO = {
    'address': 'г. Москва, ул. Ленина 104',
    'phone': '+7 495 432 31 90',
    'working_hours': 'с 10 до 20',
}

def get_template(template_name, template_context):
    template_filepath = f'{template_name}.html'
    return render_to_string(template_filepath, template_context)


def calculate_price(weight, volume):
    if not volume:
        volume = sum(VOLUME_RANGE.values()) / (len(VOLUME_RANGE) or 1)
    if not weight:
        weight = sum(WEIGHT_RANGE.values()) / (len(WEIGHT_RANGE) or 1)
    price = weight * volume * 100
    return round(price)


def start(update: Update, context):
    #  fetch params from url

    utm_source= ''
    if update.message:
        _, *utm_source = update.message.text.split()

    user, is_new_user = User.objects.get_or_create(
        tg_username=update.effective_user.username,
        chat_id=update.effective_chat.id,
    )
    context.user_data['user'] = user

    if is_new_user and utm_source:
        context.user_data['utm_source'] = utm_source[0]

    has_boxes = user.boxes.all().count()
    reply_text = f'Здравствуйте {update.effective_user.username}!\n'
    if user.from_owner:
        buttons = [
            [InlineKeyboardButton("Посмотреть промокоды", callback_data='owner_promos')],
            [InlineKeyboardButton("Посмотреть просроченные боксы", callback_data='unpaid_boxes')],
            [InlineKeyboardButton("Посмотреть открытые трансферы", callback_data='transfers')],
        ]
    elif has_boxes:
        buttons = [
            [InlineKeyboardButton("Список ваших боксов", callback_data='client_listboxes')],
            [InlineKeyboardButton("Купить еще один бокс", callback_data='client_buy_box')],
        ]
    else:
        reply_text += get_template('new_client_welcome', {})
        buttons = [
            [InlineKeyboardButton("Купить бокс", callback_data='client_buy_box')],
        ]
    reply_markup = InlineKeyboardMarkup(buttons)
    context.bot.send_message(text=reply_text, reply_markup=reply_markup, chat_id=update.effective_chat.id)


def owner_promos(update: Update, context):
    query = update.callback_query
    query.answer()
    promos = Promocodes.objects.all()

    reply_text = 'Действующих промокодов нет'
    if promos:
        promo_html = [get_template('promos', {'promo': promo}) for promo in promos]
        reply_text = '\n'.join(promo_html)

    buttons = [
        [InlineKeyboardButton(f'В начало', callback_data=f'start')],
    ]

    reply_markup = InlineKeyboardMarkup(buttons)
    query.bot.send_message(text=reply_text, reply_markup=reply_markup, chat_id=update.effective_chat.id)


def client_listboxes(update: Update, context):
    query = update.callback_query
    query.answer()
    boxes = context.user_data['user'].boxes.all()
    reply_text = 'Список ваших боксов\n'
    buttons = []
    for box in boxes:
        button_text = f'Бокс номер {box.id} весом {box.weight}, оплачен по {box.paid_till}'
        buttons.append(
            [InlineKeyboardButton(button_text, callback_data=f'client_show_box_{box.id}')]
        )
    buttons.append([InlineKeyboardButton('В начало', callback_data=f'start')])
    reply_markup = InlineKeyboardMarkup(buttons)
    query.bot.send_message(text=reply_text, reply_markup=reply_markup, chat_id=update.effective_chat.id)


def client_show_box(update: Update, context):
    query = update.callback_query
    query.answer()
    box_id = int(query.data.split('_')[-1])
    box = Box.objects.get(pk=box_id)
    context.user_data['current_box'] = box

    reply_text = get_template('showbox', {'box': box})
    buttons = [
        [InlineKeyboardButton(f'Заказать доставку всех вещей', callback_data=f'123')],
        [InlineKeyboardButton(f'Заказать доставку части вещей', callback_data=f'123')],
        [InlineKeyboardButton(f'QR код чтобы забрать самостоятельно', callback_data=f'123')]
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    query.bot.send_message(text=reply_text, reply_markup=reply_markup, chat_id=update.effective_chat.id)


def client_buy_box(update: Update, context):
    query = update.callback_query
    query.answer()

    reply_text = 'Укажите вес вещей, которые вы хотите хранить в боксе:'

    buttons = []
    for weight_k, weight_v in WEIGHT_RANGE.items():
        buttons.append(
            [InlineKeyboardButton(weight_k, callback_data=f'client_set_weight_{weight_v}')]
        )
    reply_markup = InlineKeyboardMarkup(buttons)
    query.bot.send_message(text=reply_text, reply_markup=reply_markup, chat_id=update.effective_chat.id)


def client_set_weight(update: Update, context):
    query = update.callback_query
    query.answer()

    weight = int(query.data.split('_')[-1])
    context.user_data['weight'] = weight

    reply_text = ''
    if not weight:
        reply_text = 'Не переживайте, наши грузчики взвесят ваш груз. ' \
                     'Однако будьте готовы к тому, что цена может измениться\n\n'

    reply_text += 'Теперь укажите объем груза. Объем рассчитывается как перемножение' \
                  ' трех величин в метрах: высоты, ширины и длины:'
    buttons = []
    for volume_k, volume_v in VOLUME_RANGE.items():
        buttons.append(
            [InlineKeyboardButton(volume_k, callback_data=f'client_set_volume_{volume_v}')]
        )
    reply_markup = InlineKeyboardMarkup(buttons)
    query.bot.send_message(text=reply_text, reply_markup=reply_markup, chat_id=update.effective_chat.id)


def client_set_volume(update: Update, context):
    query = update.callback_query
    query.answer()

    volume = float(query.data.split('_')[-1])
    price = calculate_price(context.user_data['weight'], volume)
    context.user_data['volume'] = volume
    context.user_data['price'] = price

    reply_text = ''
    if not context.user_data['weight'] and not volume:
        reply_text = 'Цена бокса зависит от веса и объема.' \
                     'После того, как эти величины измерят грузчики, вам сообщат цену\n\n'
    elif not volume:
        reply_text = 'Не переживайте, наши грузчики измерят размеры вашего груза. ' \
                     'Однако будьте готовы к тому, что цена может измениться' \
                     '\n\n'
    if price:
        reply_text += f'Цена вашего бокса составляет: {price} руб. в месяц\n\n' \
                      f'Укажите период аренды:'

    buttons = [
        [InlineKeyboardButton(f'1 месяц', callback_data=f'client_rent_period_1')],
        [InlineKeyboardButton(f'3 месяца', callback_data=f'client_rent_period_3')],
        [InlineKeyboardButton(f'6 месяцев', callback_data=f'client_rent_period_6')],
        [InlineKeyboardButton(f'12 месяцев', callback_data=f'client_rent_period_12')],
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    query.bot.send_message(text=reply_text, reply_markup=reply_markup, chat_id=update.effective_chat.id)


def client_rent_period(update: Update, context):
    query = update.callback_query
    query.answer()

    user = context.user_data['user']

    period = int(query.data.split('_')[-1])
    context.user_data['period'] = period

    data_for_transfer_request = f'client_ask_phone'
    if user.phone:
        data_for_transfer_request = f'client_ask_address'

    reply_text = 'Как ваши вещи окажутся на складе?'
    buttons = [
        [InlineKeyboardButton(f'Нужно забрать вещи по адресу', callback_data=data_for_transfer_request)],
        [InlineKeyboardButton(f'Доставлю свои вещи сам', callback_data=f'client_self_transfer')],
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    query.bot.send_message(text=reply_text, reply_markup=reply_markup, chat_id=update.effective_chat.id)


def client_ask_phone(update: Update, context):

    # is asking phone
    context.user_data['ask_phone'] = True
    reply_text = 'Пожалуйста, введите ваш номер телефона:'
    context.bot.send_message(text=reply_text, chat_id=update.effective_chat.id)

def client_ask_address(update: Update, context):

    # is asking address
    context.user_data['ask_address'] = True
    reply_text = 'Пожалуйста, введите ваш адрес:'
    context.bot.send_message(text=reply_text, chat_id=update.effective_chat.id)

def client_ask_time_arrive(update: Update, context):

    reply_text = 'В какое время вам удобно, чтобы приехали наши грузчики?'
    buttons = [
        [InlineKeyboardButton(f'9-13', callback_data=f'client_time_arrive_9-13')],
        [InlineKeyboardButton(f'13-18', callback_data=f'client_time_arrive_13-18')],
        [InlineKeyboardButton(f'18-22', callback_data=f'client_time_arrive_18-22')],
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    context.bot.send_message(text=reply_text, reply_markup=reply_markup, chat_id=update.effective_chat.id)


def client_time_arrive(update: Update, context):
    query = update.callback_query
    query.answer()

    time_arrive = query.data.split('_')[-1]
    context.user_data['time_arrive'] = time_arrive

    reply_text = 'Подтвердите согласие на обработку персональных данных. Полный текст доступен по адресу:' \
                 'http://some.url/text.pdf'
    buttons = [
        [InlineKeyboardButton(f'Согласен на обработку перс.данных', callback_data=f'client_save_transfer')],
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    context.bot.send_message(text=reply_text, reply_markup=reply_markup, chat_id=update.effective_chat.id)


def client_save_transfer(update: Update, context):
    query = update.callback_query
    query.answer()

    # save user phone & address in DB
    user = context.user_data['user']
    if context.user_data.get('phone'):
        user.phone = context.user_data['phone']
    user.address = context.user_data['address']
    user.save()

    # save box in DB
    box = Box.objects.create(
        user=context.user_data['user'],
        weight=context.user_data['weight'],
        volume=context.user_data['volume'],
        paid_from=datetime.now(),
        paid_till=datetime.now() + timedelta(days = context.user_data['period'] * 30),
        description='',
    )

    # save transfer in DB
    TransferRequest.objects.create(
        box=box,
        transfer_type=0,
        address=context.user_data['address'],
        time_arrive=context.user_data['time_arrive'],
        is_complete=False,
    )

    utm_source = context.user_data.get('utm_source')
    if utm_source:
        context.user_data['user'].utm_source = utm_source
        context.user_data['user'].save()

    reply_text = 'Спасибо за ваш заказ! Наши грузчики позвонят вам за 1 час до приезда'
    buttons = [
        [InlineKeyboardButton('В начало', callback_data=f'start')]
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    query.bot.send_message(text=reply_text, reply_markup=reply_markup, chat_id=update.effective_chat.id)

def client_self_transfer(update: Update, context):
    query = update.callback_query
    query.answer()

    reply_text = get_template('storage_info', {'storage': STORAGE_INFO})

    # save box in DB
    Box.objects.create(
        user=context.user_data['user'],
        weight=context.user_data['weight'],
        volume=context.user_data['volume'],
        paid_from=datetime.now(),
        paid_till=datetime.now() + timedelta(days = context.user_data['period'] * 30),
        description='',
    )

    # save utm_source for new users with completed order
    utm_source = context.user_data.get('utm_source')
    if utm_source:
        context.user_data['user'].utm_source = utm_source
        context.user_data['user'].save()

    buttons = [
        [InlineKeyboardButton('В начало', callback_data=f'start')]
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    query.bot.send_message(text=reply_text, reply_markup=reply_markup, chat_id=update.effective_chat.id)


def message_handler(update, context):
    if context.user_data.get('ask_phone'):
        context.user_data['phone'] = update.message.text
        context.user_data['ask_phone'] = False
        client_ask_address(update, context)
    elif context.user_data.get('ask_address'):
        context.user_data['address'] = update.message.text
        context.user_data['ask_address'] = False
        client_ask_time_arrive(update, context)



def error_handler_function(update, context):
    print(f"Update: {update} caused error: {context.error}")


def unpaid_boxes(update: Update, context):
    query = update.callback_query
    query.answer()
    current_datetime=datetime.now()
    boxes = Box.objects.filter(paid_till__lte=current_datetime).prefetch_related('user')
    reply_text = 'Просроченных боксов нету'
    unpaix_boxes_html = [get_template('unpaid_boxes', {'box': box}) for box in boxes]
    reply_text = '\n'.join(unpaix_boxes_html)        
    context.bot.send_message(text=reply_text,  chat_id=update.effective_chat.id, parse_mode=ParseMode.HTML)


def transfers(update: Update, context):
    query = update.callback_query
    query.answer()
    transfers = TransferRequest.objects.filter(is_complete=False)[:8]
    reply_text = 'Заявок на перевозку нет'
    buttons = []
    for transfer in transfers:
        reply_text = 'Список заявок на перевозку грузов\n'
        button_text = f'Бокс № {transfer.box.id}, {transfer.transfer_type}'
        buttons.append(
            [InlineKeyboardButton(button_text, callback_data=f'transfer_box_{transfer.id}')],
        )
    buttons.append([InlineKeyboardButton(f'В начало', callback_data=f'start')])
    reply_markup = InlineKeyboardMarkup(buttons)
    query.bot.send_message(text=reply_text, reply_markup=reply_markup, chat_id=update.effective_chat.id)


def transfer_box(update: Update, context):
    query = update.callback_query
    query.answer()

    transfer_id = query.data.split('_')[-1]

    transfer_request = TransferRequest.objects.get(id=transfer_id)
    reply_text = get_template('transfer_info', {'transfer': transfer_request})

    buttons = [
        [InlineKeyboardButton(f'Пометить трансфер как выполненный', callback_data=f'transfer_complete_{transfer_id}')],
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    query.bot.send_message(text=reply_text, reply_markup=reply_markup, chat_id=update.effective_chat.id)


def transfer_complete(update: Update, context):
    query = update.callback_query
    query.answer()

    transfer_id = query.data.split('_')[-1]

    TransferRequest.objects.filter(id=transfer_id).update(is_complete=True)
    reply_text = f'Трансфер {transfer_id} выполнен'
    buttons = [
        [InlineKeyboardButton(f'В начало', callback_data=f'start')],
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    query.bot.send_message(text=reply_text, reply_markup=reply_markup, chat_id=update.effective_chat.id)




if __name__ == '__main__':
    env = Env()
    env.read_env()
    tg_token = env('TELEGRAM_TOKEN')

    updater = Updater(tg_token, use_context=True)
    app = updater.dispatcher

    # common handlers
    app.add_handler(CallbackQueryHandler(start, pattern='^start$'))

    # owner handlers
    app.add_handler(CallbackQueryHandler(owner_promos, pattern='^owner_promos$'))
    app.add_handler(CallbackQueryHandler(unpaid_boxes, pattern='^unpaid_boxes'))       
    app.add_handler(CallbackQueryHandler(transfers, pattern='^transfers$'))
    app.add_handler(CallbackQueryHandler(transfer_box, pattern='^transfer_box_'))
    app.add_handler(CallbackQueryHandler(transfer_complete, pattern='^transfer_complete_'))

    # existing client handlers
    app.add_handler(CallbackQueryHandler(client_listboxes, pattern='^client_listboxes$'))
    app.add_handler(CallbackQueryHandler(client_show_box, pattern='^client_show_box_'))

    # new box handlers
    app.add_handler(CallbackQueryHandler(client_buy_box, pattern='^client_buy_box$'))
    app.add_handler(CallbackQueryHandler(client_set_weight, pattern='^client_set_weight_'))
    app.add_handler(CallbackQueryHandler(client_set_volume, pattern='^client_set_volume_'))
    app.add_handler(CallbackQueryHandler(client_rent_period, pattern='^client_rent_period_'))
    app.add_handler(CallbackQueryHandler(client_ask_phone, pattern='^client_ask_phone$'))
    app.add_handler(CallbackQueryHandler(client_ask_address, pattern='^client_ask_address$'))
    app.add_handler(CallbackQueryHandler(client_time_arrive, pattern='^client_time_arrive_'))
    app.add_handler(CallbackQueryHandler(client_save_transfer, pattern='^client_save_transfer'))
    app.add_handler(CallbackQueryHandler(client_self_transfer, pattern='^client_self_transfer$'))

    app.add_handler(CommandHandler("start", start))

    app.add_handler(MessageHandler(Filters.text, message_handler))
    app.add_error_handler(error_handler_function)

    updater.start_polling(1.0)
    updater.idle()
