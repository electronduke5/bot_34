import re

from aiogram.enums import ParseMode

from aiogram.types import ContentType, URLInputFile, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv
import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiohttp import ClientSession
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота
load_dotenv()

API_TOKEN = os.getenv("BOT_TOKEN")
GRAPHQL_URL = os.getenv("GRAPHQL_API_URL")

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Глобальная сессия для HTTP-запросов
session = None


# ===== States (FSM) =====
class PostCreation(StatesGroup):
    title = State()
    image = State()
    rarity = State()


async def on_startup():
    global session
    session = ClientSession()
    print("Бот запущен")


async def on_shutdown():
    await session.close()
    await bot.close()
    print("Бот остановлен")


def format_number_with_commas(number: int) -> str:
    """
    Форматирует число, добавляя запятые как разделители разрядов.

    Args:
        number: Целое число для форматирования

    Returns:
        Строковое представление числа с разделителями


    """
    return "{:,}".format(number).replace(",", "\.")


async def register_user(user_data: dict):
    """Регистрация нового пользователя через GraphQL API"""
    mutation = """
    mutation CreateUser($firstName: String!, $lastName: String, $username: String, $tgId: String!) {
        createUser(
            first_name: $firstName
            last_name: $lastName
            username: $username
            tg_id: $tgId
        ) {
            id
            username
            tg_id
            points
            gems
        }
    }
    """

    variables = {

        "tgId": str(user_data['id']),
        "username": user_data.get('username', f"user_{user_data['id']}"),
        "firstName": user_data.get('first_name', ''),
        "lastName": user_data.get('last_name', '')

    }

    async with session.post(GRAPHQL_URL, json={'query': mutation, 'variables': variables}) as resp:
        data = await resp.json()
        print(data)
        return data


async def get_or_create_user(message: Message):
    """Проверяет существование пользователя и регистрирует при необходимости"""
    user = message.from_user
    query = """
    query UserProfile($tg_id: String!) {
        userProfile(tg_id: $tg_id) {
            user{
                id
                tg_id
                first_name
                username
            }
        }
    }
    """

    # Проверяем существование пользователя
    async with session.post(GRAPHQL_URL, json={
        'query': query,
        'variables': {'tg_id': str(user.id)}
    }) as resp:
        data = await resp.json()
        logger.info(f"Data from userProfile: {data}")

        if not data.get('data', {}).get('userProfile'):
            # Пользователь не найден - регистрируем
            user_data = {
                'id': user.id,
                'username': user.username,
                'first_name': user.first_name,
                'last_name': user.last_name
            }
            await register_user(user_data)
            print(f"Зарегистрирован новый пользователь: {user.id}")


@dp.message(Command('chat_id'))
async def get_chat_id(message: Message):
    response = (
        f"Ваш ID чата:\n\n  "
        f"`{str(message.chat.id)}`"
    )
    await message.answer(response, parse_mode=ParseMode.MARKDOWN_V2)


# Обработчик команды /start
@dp.message(Command('start'))
async def send_welcome(message: Message):
    await get_or_create_user(message)
    welcome_text = (
        "👋 Привет! Я бот для работы с коллекциями.\n\n"
        "Доступные команды:\n"
        "/chance - Проверить шансы\n"
        "/profile - Показать профиль\n"
        "/create <Название коллекции>\n"
        "/help - Помощь"
    )
    await message.answer(welcome_text)


# Обработчик команды /top
@dp.message(Command('top'))
async def send_welcome(message: Message):
    query = """
        query TopUsers{
            userTop{
                tg_id
                first_name
                points
            }
        }
    """
    try:
        async with session.post(GRAPHQL_URL, json={
            'query': query,
        }) as resp:
            data = await resp.json()

            if 'errors' in data:
                await message.answer("⚠ Ошибка при получении данных")
                return

            users_top = data['data']['userTop']
            response = f"*Топ компании*\n"
            response += f"`··············` \n"
            user_position = None
            for index, user in enumerate(users_top, start=1):
                response += f"*{index}\.* [{user['first_name']}](tg://user?id={user['tg_id']}) 🎖️ {format_number_with_commas(user['points'])} _pts_\n"

                # Проверяем, является ли этот пользователь текущим
                if str(user['tg_id']) == str(message.from_user.id):
                    user_position = index

            # Добавляем информацию о позиции текущего пользователя
            if user_position is not None:
                response += f"\n> Вы на *{user_position}* месте\n"
            else:
                response += f"\n> Вы пока не в топе\n"

            await message.answer(response, parse_mode=ParseMode.MARKDOWN_V2)

    except Exception as e:
        await message.answer("🚫 Произошла ошибка при запросе к серверу")
        print(f"Error: {e}")


def get_rarity_count(posts_count_by_rarity, rarity_name):
    """Возвращает количество постов указанной редкости"""
    for item in posts_count_by_rarity:
        if item['rarity'].lower() == rarity_name.lower():
            return item['count']
    return 0  # Если редкость не найдена


def escape_markdown(text: str) -> str:
    return re.sub(r'([_*[\]()~>#\+\-=|{}.!])', r'\\\1', text)


# Обработчик команды /chance
@dp.message(Command('chance'))
async def send_chance_info(message: Message):
    await get_or_create_user(message)
    user_id = message.from_user.id
    query = """
    mutation getRandomPost($tg_id: String!, $chat_id: String!) {
        getRandomPost(tg_id: $tg_id, chat_id: $chat_id) {
            post{
                id
                title
                image_url
                rarity {
                    name
                    points
                }
                collection{
                    name
                    postsCountByRarity{
                        rarity
                        count
                    }
                }
            }
            is_exist
            count_post_rarity 
        }
    }
    """

    try:
        print(f"tg_id in chance: {user_id}")
        if user_id == message.chat.id:
            await message.answer("❗️ *Эта команда доступна только в чате*", parse_mode=ParseMode.MARKDOWN_V2)
            return
        async with session.post(GRAPHQL_URL, json={
            'query': query,
            'variables': {
                'tg_id': str(user_id),
                'chat_id': str(message.chat.id)
            }
        }) as resp:
            data = await resp.json()
            print(data)

            if 'errors' in data:
                error = data['errors'][0]
                if error.get('extensions', {}).get('code') == 'TIMEOUT':
                    timeout_msg = error['message']

                    await message.answer(
                        f"[{message.from_user.first_name}](tg://user?id={message.from_user.id}) *сосать*, жди\n"
                        f"> {escape_markdown(timeout_msg)}\n"
                        "до следующей попытки",
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                    return

                await message.answer("⚠ Ошибка при получении данных")
                return

            post = data['data']['getRandomPost']['post']
            is_exist = data['data']['getRandomPost']['is_exist']
            count = data['data']['getRandomPost']['count_post_rarity']
            # Колчиество постов данной редкости в коллекции
            count_post_rarity = get_rarity_count(post.get('collection').get('postsCountByRarity'),
                                                 post['rarity']['name'])

            response = (
                f"*{post['title']}*\n"
                f"> {post['rarity']['name']}\n"
                f"{count} из {count_post_rarity} · {'баян' if is_exist else 'Новый\!'}\n"
                f"`··············`\n"
                fr"🎖️ _\+{post['rarity']['points']} очков_")

            # Если есть изображение
            if post.get('image_url'):
                await message.answer_photo(
                    photo=URLInputFile(post['image_url']),
                    caption=response,
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            else:
                await message.answer(response, parse_mode=ParseMode.MARKDOWN_V2)

    except Exception as e:
        await message.answer("🚫 Произошла ошибка при запросе к серверу")
        print(f"Error: {e}")


def count_by_rarity(items, target_rarity):
    return next((item['count'] for item in items if item['rarity'] == target_rarity), 0)


async def fetch_and_render_profile(user_id: str, chat_id: str, edit_message: Message = None) -> tuple[
    str, InlineKeyboardMarkup]:
    """Получает данные профиля и формирует ответ"""
    query = """
    query UserProfile($tg_id: String!, $chat_id: String) {
        userProfile(tg_id: $tg_id, chat_id: $chat_id) {
            user {
                id
                tg_id
                first_name
                last_name
                username
                points
                gems
                timeout
                collections {
                    id
                    name
                    postsCount
                }
            }
            collection {
                name
                postsCount
                postsCountByRarity {
                    rarity
                    count
                }
            }
            userPostsCount {
                rarity
                count
            }
        }
    }
    """

    try:
        async with session.post(GRAPHQL_URL, json={
            'query': query,
            'variables': {'tg_id': user_id, 'chat_id': chat_id}
        }) as resp:
            data = await resp.json()

            if 'errors' in data:
                raise ValueError("GraphQL error")

            RARITY_CONFIG = [
                ('🩵', 'Обычный'),
                ('💚', 'Редкий'),
                ('💙', 'Сверхредкий'),
                ('💜', 'Эпический'),
                ('❤️', 'Мифический'),
                ('⭐️', 'Легендарный')
            ]

            profile_data = data['data']['userProfile']
            user = profile_data['user']
            collection = profile_data['collection']
            user_counts = profile_data['userPostsCount']

            response_parts = [
                f"*{escape_markdown(user['first_name'])}*",
                "`··············`"
            ]

            if not collection:
                response_parts.extend([
                    f"💎 {format_number_with_commas(user['gems'])} гемов",
                    f"🎖️ {format_number_with_commas(user['points'])} очков",
                    "📂 Коллекции:"
                ])
            else:
                user_post_count = sum(rarity['count'] for rarity in user_counts)
                response_parts.extend([
                    f"📂 Коллекция чата: *{escape_markdown(collection['name'])}*",
                    f"🖼 *{user_post_count} из {collection['postsCount']} постов*",
                    "`··············`",
                    *(
                        f"{emoji} {rarity}: {count_by_rarity(user_counts, rarity)} из {count_by_rarity(collection['postsCountByRarity'], rarity)}"
                        for emoji, rarity in RARITY_CONFIG
                    ),
                    "`··············`",
                    f"💎 {format_number_with_commas(user['gems'])} гемов",
                    f"🎖️ {format_number_with_commas(user['points'])} очков",
                ])

            response = "\n".join(response_parts)
            builder = None

            if collections := user['collections']:
                builder = InlineKeyboardBuilder()
                if str(user_id) == str(chat_id):
                    for col in collections:
                        builder.add(InlineKeyboardButton(
                            text=f"{col['name']} ({col['postsCount']})",
                            callback_data=f"show_collection_{col['id']}"
                        ))
                    builder.adjust(1)
                else:
                    builder = None

            return response, builder.as_markup() if builder else None

    except Exception as e:
        logger.error(f"Profile fetch error: {e}")
        raise


# Обработчик команды /profile
@dp.message(Command('profile'))
async def send_user_profile(message: Message):
    await get_or_create_user(message)
    try:
        response, markup = await fetch_and_render_profile(
            user_id=str(message.from_user.id),
            chat_id=str(message.chat.id)
        )

        await message.answer(
            response,
            reply_markup=markup,
            parse_mode=ParseMode.MARKDOWN_V2
        )
    except ValueError:
        await message.answer("⚠ Ошибка при получении профиля")
    except Exception:
        await message.answer("🚫 Произошла ошибка при запросе профиля")


@dp.message(Command('create'))
async def create_collection(message: Message):
    # Проверяем/регистрируем пользователя
    await get_or_create_user(message)

    # Разделяем команду и аргументы
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("ℹ Использование: /create <Название коллекции>")
        return

    collection_name = args[1].strip()
    tg_id = str(message.from_user.id)

    # GraphQL мутация для создания коллекции
    mutation = """
    mutation CreateCollection($tg_id: String!, $name: String!) {
        createCollection(tg_id: $tg_id, name: $name) {
            id
            name
            user {
                id
                first_name
                last_name
                username
                tg_id
            }
        }
    }
    """

    try:
        async with session.post(GRAPHQL_URL, json={
            'query': mutation,
            'variables': {
                'name': collection_name,
                'tg_id': str(tg_id)
            }
        }) as resp:
            data = await resp.json()

            if 'errors' in data:
                error_msg = data['errors'][0]['extensions']['debugMessage']
                await message.answer(f"❌ Ошибка при создании коллекции: {error_msg}")
                return

            collection = data['data']['createCollection']
            await message.answer(
                f"✅ Коллекция создана!\n\n"
                f"Название: {collection['name']}\n"
                f"ID: {collection['id']}"
            )

    except Exception as e:
        await message.answer("🚫 Произошла ошибка при создании коллекции")
        print(f"Error: {e}")


@dp.callback_query(lambda c: c.data.startswith('show_collection_'))
async def show_collection_info(callback: CallbackQuery):
    collection_id = int(callback.data.split('_')[2])  # Теперь индекс 2

    query = """
    query CollectionInfo($id: Int!) {
        collectionInfo(id: $id) {
            id
            name
            postsCount
            chat_id
            postsCountByRarity{
                rarity
                count
            }
        }
    }
    """

    try:
        async with session.post(GRAPHQL_URL, json={
            'query': query,
            'variables': {'id': collection_id}
        }) as resp:

            data = await resp.json()

            if 'errors' in data:
                await callback.answer("⚠ Ошибка при получении коллекции")
                return

            collection = data['data']['collectionInfo']

            if collection['chat_id'] is None:
                collection['chat_id'] = "Не привязана"
            RARITY_CONFIG = [
                ('🩵', 'Обычный'),
                ('💚', 'Редкий'),
                ('💙', 'Сверхредкий'),
                ('💜', 'Эпический'),
                ('❤️', 'Мифический'),
                ('⭐️', 'Легендарный')
            ]
            rarity_lines = [
                f"{emoji} {rarity}: {count_by_rarity(collection['postsCountByRarity'], rarity)}"
                for emoji, rarity in RARITY_CONFIG
            ]

            response = (
                    f"📦 Коллекция: {collection['name']}\n\n"
                    f"🔗 Привязка к чату: {escape_markdown(collection['chat_id'])}\n\n"
                    f"📌 Всего постов: {collection['postsCount']}\n\n"
                    f"📊 Посты по редкостям:\n"
                    f"`··············`\n"
                    + "\n".join(rarity_lines)
            )

            # Создаем клавиатуру
            keyboard = InlineKeyboardBuilder()

            # Кнопка "Назад"
            keyboard.add(InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data="back_to_profile"
            ))
            keyboard.add(InlineKeyboardButton(
                text="➕ Добавить пост",
                callback_data=f"add_post_{collection_id}"
            ))
            logger.info(f"chatId: {collection.get('chat_id')}")
            # Кнопка привязки/отвязки коллекции
            if collection.get('chat_id') != 'Не привязана':
                keyboard.add(InlineKeyboardButton(
                    text="❌ Отвязать от чата",
                    callback_data=f"unlink_collection_{collection_id}"
                ))
            else:
                keyboard.add(InlineKeyboardButton(
                    text="🔗 Привязать к чату",
                    callback_data=f"link_collection_{collection_id}"
                ))

            keyboard.adjust(1)  # По одной кнопке в ряд

            # Редактируем существующее сообщение
            await callback.message.edit_text(
                text=response,
                reply_markup=keyboard.as_markup(),
                parse_mode=ParseMode.MARKDOWN_V2
            )
        await callback.answer()


    except Exception as e:
        await callback.answer("🚫 Ошибка загрузки коллекции")
        print(f"Error: {e}")


@dp.callback_query(lambda c: c.data.startswith('link_collection_'))
async def link_collection(callback: CallbackQuery):
    collection_id = int(callback.data.split('_')[2])
    chat_id = callback.message.chat.id

    mutation = """
    mutation LinkCollection($id: Int!, $chat_id: String!) {
        linkCollection(
            id: $id
            chat_id: $chat_id
        ) {
            id
            name
            postsCount
            chat_id
            postsCountByRarity{
                rarity
                count
            }
        }
    }
    """

    try:
        async with session.post(GRAPHQL_URL, json={
            'query': mutation,
            'variables': {
                'id': collection_id,
                'chat_id': str(chat_id)
            }
        }) as resp:
            data = await resp.json()
            logger.info(f"Data in linkCollection method: {data}")

            if 'errors' in data:
                await callback.answer("⚠ Ошибка при привязке коллекции")
                return

            await show_collection_info(types.CallbackQuery(
                id=callback.id,
                from_user=callback.from_user,
                chat_instance=callback.chat_instance,
                message=callback.message,
                data=f"show_collection_{collection_id}",
                game_short_name=None,
                inline_message_id=None
            ))
            await callback.answer("✅ Коллекция привязана к чату")

    except Exception as e:
        # await callback.answer("🚫 Ошибка при привязке")
        print(f"Error: {e}")


@dp.callback_query(lambda c: c.data.startswith('unlink_collection_'))
async def unlink_collection(callback: CallbackQuery):
    collection_id = int(callback.data.split('_')[2])

    mutation = """
    mutation UnlinkCollection($id: Int!) {
        unlinkCollection(id: $id) {
            id
            name
            postsCount
            chat_id
            postsCountByRarity{
                rarity
                count
            }
        }
    }
    """

    try:
        async with session.post(GRAPHQL_URL, json={
            'query': mutation,
            'variables': {'id': collection_id}
        }) as resp:
            data = await resp.json()
            logger.info(f"Data in unlinkCollection method: {data}")

            if 'errors' in data:
                await callback.answer("⚠ Ошибка при отвязке коллекции")
                return

            # Обновляем информацию о коллекции
            await show_collection_info(types.CallbackQuery(
                id=callback.id,
                from_user=callback.from_user,
                chat_instance=callback.chat_instance,
                message=callback.message,
                data=f"show_collection_{collection_id}",
                game_short_name=None,
                inline_message_id=None
            ))
            await callback.answer("✅ Коллекция отвязана от чата")

    except Exception as e:
        # await callback.answer("🚫 Ошибка при отвязке")
        print(f"Error: {e}")


@dp.callback_query(lambda c: c.data == "back_to_profile")
async def back_to_profile(callback: CallbackQuery):
    try:
        response, markup = await fetch_and_render_profile(
            user_id=str(callback.from_user.id),
            chat_id=str(callback.message.chat.id),
            edit_message=callback.message
        )

        if markup:
            await callback.message.edit_text(
                text=response,
                reply_markup=markup,
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            await callback.message.edit_text(
                text=response + "\nУ вас пока нет коллекций",
                parse_mode=ParseMode.MARKDOWN_V2
            )
    except ValueError:
        await callback.answer("⚠ Ошибка при получении профиля")
    except Exception:
        await callback.answer("🚫 Ошибка загрузки профиля")


@dp.callback_query(lambda c: c.data.startswith('add_post_'))
async def start_add_post(callback: CallbackQuery, state: FSMContext):
    collection_id = int(callback.data.split('_')[2])

    # Сохраняем ID коллекции в состоянии
    await state.update_data(collection_id=collection_id)

    # Запрашиваем название поста
    await callback.message.answer(
        "📝 Введите название поста:",
    )
    # Устанавливаем состояние ожидания названия
    await state.set_state(PostCreation.title)
    await callback.answer()


@dp.message(PostCreation.title, F.text.len() <= 100)
async def process_post_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)

    await message.answer(
        "🖼 Отправьте изображение или GIF для поста:",
    )
    await state.set_state(PostCreation.image)


@dp.message(PostCreation.title)
async def process_long_title(message: Message):
    await message.answer("❌ Слишком длинное название (максимум 100 символов)")


@dp.message(PostCreation.image, F.content_type.in_({ContentType.PHOTO, ContentType.ANIMATION}))
async def process_post_media(message: Message, state: FSMContext):
    media_data = {}

    if message.photo:
        media_data = {'type': 'photo', 'file_id': message.photo[-1].file_id}
    elif message.animation:
        media_data = {'type': 'animation', 'file_id': message.animation.file_id}

    await state.update_data(media=media_data)
    # Клавиатура с вариантами редкости
    await process_rarity_selection(message, state)


dp.message(PostCreation.image, F.text == "Пропустить")


async def get_rarities():
    """Получает список редкостей из GraphQL API"""
    query = """
    query RarityList {
        rarityList {
            id
            name
        }
    }
    """
    try:
        async with session.post(GRAPHQL_URL, json={'query': query}) as resp:
            data = await resp.json()
            return data['data']['rarityList']
    except Exception as e:
        print(f"Error fetching rarities: {e}")
        return [
            {"id": 1, "name": "Обычный"},
            {"id": 2, "name": "Редкий"},
            {"id": 3, "name": "Сверхредкий"},
            {"id": 4, "name": "Эпический"},
            {"id": 5, "name": "Мифический"},
            {"id": 6, "name": "Легендарный"}
        ]


async def process_rarity_selection(message: Message, state: FSMContext):
    rarities = await get_rarities()

    builder = InlineKeyboardBuilder()
    for rarity in rarities:
        builder.add(InlineKeyboardButton(
            text=rarity['name'],
            callback_data=f"rarity_{rarity['id']}"
        ))
    builder.adjust(2)

    await message.answer(
        "🎚 Выберите редкость поста:",
        reply_markup=builder.as_markup()
    )
    await state.set_state(PostCreation.rarity)


@dp.callback_query(PostCreation.rarity, lambda c: c.data.startswith('rarity_'))
async def complete_post_creation(callback: CallbackQuery, state: FSMContext):
    rarity_id = int(callback.data.split('_')[1])
    data = await state.get_data()

    # Формируем медиа-группу если есть файлы
    media_url = None
    if data.get('media'):
        file = await bot.get_file(data['media']['file_id'])
        media_url = f"https://api.telegram.org/file/bot{API_TOKEN}/{file.file_path}"

    # Отправляем данные на сервер
    mutation = """
    mutation CreatePost($title: String!, $image_url: String!, $rarity_id: Int!, $collection_id: Int!) {
    createPost(
        title: $title
        image_url: $image_url 
        rarity_id: $rarity_id
        collection_id: $collection_id
    ) {
        id
        title
        image_url
        rarity {
            name
            points
        }
        collection {
            id
            name
        }
    }
    }
    """

    variables = {
        "title": data['title'],
        "image_url": media_url,
        "rarity_id": rarity_id,
        "collection_id": data['collection_id'],
    }

    try:
        async with session.post(GRAPHQL_URL, json={
            'query': mutation,
            'variables': variables
        }) as resp:
            result = await resp.json()
            print(f"result: {result}")
            print(f"mediaUrl: {media_url}")

            if 'errors' in result:
                error_msg = result['errors'][0]['message']
                await callback.message.answer(f"❌ Ошибка: {error_msg}")
            else:
                post = result['data']['createPost']
                print(f"post: {post}")
                response = (
                    f"✅ Пост *{post['title'].replace('.', r'\.')}* успешно создан\!\n\n"
                    f"> {post['rarity']['name']}\n"
                    f"Коллекция: {post['collection']['name']}\n"
                    f"🎖️ _\\{post['rarity']['points']} очков_"
                )

                if data.get('media'):
                    if data['media']['type'] == 'photo':
                        await callback.message.answer_photo(
                            photo=data['media']['file_id'],
                            caption=response,
                            parse_mode=ParseMode.MARKDOWN_V2
                        )
                    else:
                        await callback.message.answer_animation(
                            animation=data['media']['file_id'],
                            caption=response,
                            parse_mode=ParseMode.MARKDOWN_V2
                        )
                else:
                    await callback.message.answer(response, parse_mode=ParseMode.MARKDOWN_V2)

    except Exception as e:
        await callback.message.answer("🚫 Ошибка при сохранении поста")
        print(f"Error: {e.args}")

    await state.clear()
    await callback.answer()


async def main():
    await on_startup()
    await dp.start_polling(bot)
    await on_shutdown()


if __name__ == '__main__':
    asyncio.run(main())
