import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from app.agent.agent import StayFlowAgent
from app.db.session import SessionLocal
from app.models import Guest

load_dotenv()

agent = StayFlowAgent()


async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not update.message or not update.message.text or not update.effective_user:
        return

    telegram_user = update.effective_user
    user_message = update.message.text

    with SessionLocal() as db:
        guest = (
            db.query(Guest)
            .filter(
                Guest.telegram_user_id == telegram_user.id,
                Guest.hotel_id == 2,
            )
            .first()
        )

        if not guest:
            guest = Guest(
                hotel_id=2,
                name=telegram_user.full_name or "Telegram Guest",
                telegram_user_id=telegram_user.id,
            )
            db.add(guest)
            db.commit()
            db.refresh(guest)

        guest_id = guest.id

    response = agent.run(
        user_message,
        guest_id=guest_id,
    )

    await update.message.reply_text(response)


def create_telegram_app() -> Application:
    token = os.getenv("TELEGRAM_BOT_TOKEN")

    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set")

    application = Application.builder().token(token).build()

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    return application


def run_telegram_bot() -> None:
    application = create_telegram_app()

    print("StayFlow Telegram AI bot is running...")

    application.run_polling()


if __name__ == "__main__":
    run_telegram_bot()
