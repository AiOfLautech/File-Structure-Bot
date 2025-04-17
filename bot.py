import os
import json
import shutil
import tempfile
import tarfile
import logging
from urllib.parse import urljoin
from fpdf import FPDF
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# Set up logging for console output
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment variables for deployment
TOKEN = os.getenv("7366358800:AAF2684s1_Ipw-4xnazbdU6lXrYHRG0mcnM")
WEBHOOK_URL = os.getenv("https://file-structure-bot.onrender.com")
PORT = int(os.getenv("PORT", 8443))

# Directories for uploads and zips
UPLOAD_DIR = "uploads"
ZIP_DIR = "zips"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(ZIP_DIR, exist_ok=True)

# User states and data
user_states = {}
user_data = {}

# Predefined templates
TEMPLATES = {
    "web": [
        "project/",
        "project/index.html",
        "project/css/style.css",
        "project/js/script.js"
    ],
    "python": [
        "project/",
        "project/main.py",
        "project/requirements.txt",
        "project/utils/__init__.py"
    ]
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message with instructions."""
    await update.message.reply_text(
        "Welcome to the File Structure Bot!\n"
        "I can create zipped file structures, convert text to PDF, and more.\n"
        "Commands:\n"
        "/createzip [zip|tar.gz] - Upload a text/JSON file for a structure\n"
        "/quickcreate [zip|tar.gz] - Send a structure directly\n"
        "/createpdf - Convert text to PDF\n"
        "/template [web|python] - Use a predefined structure\n"
        "/api - Simulate API interactions\n"
        "/help - Show this message"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help message with all commands."""
    await update.message.reply_text(
        "Available commands:\n"
        "/createzip [zip|tar.gz] - Upload a text or JSON file with structure\n"
        "/quickcreate [zip|tar.gz] - Send structure in a message\n"
        "/createpdf - Send text or a file to create a PDF\n"
        "/template [web|python] - Create a predefined structure\n"
        "/api - Simulate API interactions\n"
        "/help - Show this message\n\n"
        "Example structure file:\n"
        "folder1/\n"
        "folder1/file1.txt\n"
        "Or JSON:\n"
        '[{"path": "file1.txt", "content": "Hello"}]'
    )

async def createzip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start process to create a zip from a structure file."""
    user_id = update.message.from_user.id
    args = context.args
    format_type = args[0] if args and args[0] in ["zip", "tar.gz"] else "zip"
    user_states[user_id] = {"state": "creating_structure", "format": format_type}
    await update.message.reply_text(
        f"Please send a text or JSON file with the file structure.\n"
        f"Format: {format_type}\n"
        "Text example: folder1/\nfolder1/file.txt\n"
        "JSON example: [{\"path\": \"file.txt\", \"content\": \"Hello\"}]"
    )

async def quickcreate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start process to create a zip from direct text input."""
    user_id = update.message.from_user.id
    args = context.args
    format_type = args[0] if args and args[0] in ["zip", "tar.gz"] else "zip"
    user_states[user_id] = {"state": "quick_structure", "format": format_type}
    await update.message.reply_text(
        f"Please send the file structure, one path per line.\n"
        f"Format: {format_type}\n"
        "Example:\n"
        "folder1/\n"
        "folder1/file1.txt"
    )

async def createpdf_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start process to create a PDF from text."""
    user_id = update.message.from_user.id
    user_states[user_id] = {"state": "creating_pdf"}
    await update.message.reply_text(
        "Please send the text content for the PDF or upload a text file.\n"
        "Example: Hello, this is my PDF content!"
    )

async def template_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create a predefined structure from a template."""
    user_id = update.message.from_user.id
    args = context.args
    template_name = args[0] if args else None
    if template_name not in TEMPLATES:
        await update.message.reply_text(
            f"Invalid template. Available templates: {', '.join(TEMPLATES.keys())}"
        )
        return
    format_type = args[1] if len(args) > 1 and args[1] in ["zip", "tar.gz"] else "zip"
    await create_structure_with_progress(
        update, context, TEMPLATES[template_name], format_type, f"{template_name}_structure"
    )

async def api_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Simulate API interactions with enhanced test response."""
    user_id = update.message.from_user.id
    args = context.args
    if args and args[0] == "test":
        response = {
            "Creator": "AI OF LAUTECH",
            "Status": True,
            "Version": "1.0.0",
            "Timestamp": context.bot.get_timestamp(),
            "Message": "API test successful!"
        }
        await update.message.reply_text(
            "\n".join(f"{key}: {value}" for key, value in response.items())
        )
    elif args and args[0] == "create_structure" and len(args) > 1:
        try:
            json_data = json.loads(" ".join(args[1:]))
            format_type = json_data.get("format", "zip") if isinstance(json_data, dict) else "zip"
            paths = json_data if isinstance(json_data, list) else json_data.get("structure", [])
            if not paths:
                raise ValueError("No structure provided")
            await create_structure_with_progress(update, context, [(p["path"], p.get("content", "")) for p in paths], format_type, "api_structure")
        except Exception as e:
            await update.message.reply_text(f"API Error: {str(e)}")
    else:
        await update.message.reply_text(
            "API Usage:\n"
            "/api test - Test the API\n"
            "/api create_structure [json_data] - Create a structure from JSON\n"
            "/api create_pdf [text] - Create a PDF from text\n"
            "Example: /api create_structure [{\"path\": \"file.txt\", \"content\": \"Hello\"}]"
        )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle uploaded documents based on user state."""
    user_id = update.message.from_user.id
    state_info = user_states.get(user_id, {})
    state = state_info.get("state")

    if state not in ["creating_structure", "creating_pdf"]:
        await update.message.reply_text("Please use /createzip or /createpdf first.")
        return

    file = await update.message.document.get_file()
    file_name = update.message.document.file_name
    file_path = os.path.join(UPLOAD_DIR, f"{user_id}_{file_name}")
    await file.download_to_drive(file_path)

    try:
        if state == "creating_structure":
            format_type = state_info.get("format", "zip")
            paths = []
            if file_name.endswith(".json"):
                with open(file_path, 'r') as f:
                    data = json.load(f)
                if not isinstance(data, list):
                    raise ValueError("JSON must be a list of objects")
                for item in data:
                    if not isinstance(item, dict) or "path" not in item:
                        raise ValueError("Each item must be an object with a 'path' key")
                    paths.append((item["path"], item.get("content", "")))
            else:
                with open(file_path, 'r') as f:
                    paths = [(line.strip(), "") for line in f if line.strip()]

            if len(paths) > 10:
                user_states[user_id] = {
                    "state": "confirm_structure",
                    "format": format_type,
                    "paths": paths
                }
                summary = "\n".join(p[0] for p in paths[:5])
                if len(paths) > 5:
                    summary += f"\n...and {len(paths) - 5} more"
                await update.message.reply_text(
                    f"About to create {len(paths)} items:\n{summary}\n"
                    "Reply 'yes' to proceed or 'cancel' to stop."
                )
            else:
                await create_structure_with_progress(update, context, paths, format_type, "structure")

        elif state == "creating_pdf":
            with open(file_path, 'r') as f:
                text = f.read()
            await create_pdf(update, context, text)

    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
        if state != "confirm_structure":
            user_states[user_id] = None

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages based on user state."""
    user_id = update.message.from_user.id
    state_info = user_states.get(user_id, {})
    state = state_info.get("state")
    text = update.message.text

    if state == "quick_structure":
        paths = [(line.strip(), "") for line in text.split('\n') if line.strip()]
        format_type = state_info.get("format", "zip")
        if len(paths) > 10:
            user_states[user_id] = {
                "state": "confirm_structure",
                "format": format_type,
                "paths": paths
            }
            summary = "\n".join(p[0] for p in paths[:5])
            if len(paths) > 5:
                summary += f"\n...and {len(paths) - 5} more"
            await update.message.reply_text(
                f"About to create {len(paths)} items:\n{summary}\n"
                "Reply 'yes' to proceed or 'cancel' to stop."
            )
        else:
            await create_structure_with_progress(update, context, paths, format_type, "structure")
        if state != "confirm_structure":
            user_states[user_id] = None

    elif state == "creating_pdf":
        await create_pdf(update, context, text)
        user_states[user_id] = None

    elif state == "confirm_structure":
        if text.lower() == "yes":
            await create_structure_with_progress(
                update,
                context,
                state_info["paths"],
                state_info["format"],
                "structure"
            )
        elif text.lower() == "cancel":
            await update.message.reply_text("Operation canceled.")
        else:
            await update.message.reply_text("Please reply 'yes' or 'cancel'.")
        user_states[user_id] = None

    else:
        await update.message.reply_text("Please use a command like /createzip, /quickcreate, or /createpdf.")

async def create_structure_with_progress(update: Update, context: ContextTypes.DEFAULT_TYPE, paths, format_type, output_name):
    """Create a file structure with progress updates and archive it."""
    user_id = update.message.from_user.id
    total_items = len(paths)
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            for i, (path, content) in enumerate(paths, 1):
                full_path = os.path.normpath(os.path.join(temp_dir, path.lstrip('/')))
                if not full_path.startswith(temp_dir):
                    continue
                if path.endswith('/'):
                    os.makedirs(full_path, exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(full_path), exist_ok=True)
                    with open(full_path, 'w') as f:
                        f.write(content)
                if i % 5 == 0 or i == total_items:
                    await update.message.reply_text(f"Creating item {i}/{total_items}...")

            output_path = os.path.join(ZIP_DIR, f"{output_name}_{user_id}")
            if format_type == "zip":
                shutil.make_archive(output_path, 'zip', temp_dir)
                archive_path = f"{output_path}.zip"
            else:  # tar.gz
                archive_path = f"{output_path}.tar.gz"
                with tarfile.open(archive_path, "w:gz") as tar:
                    tar.add(temp_dir, arcname="")

            with open(archive_path, 'rb') as archive_file:
                await update.message.reply_document(
                    document=archive_file,
                    filename=f"{output_name}.{format_type.replace('.', '')}"
                )

            os.remove(archive_path)
            await update.message.reply_text(f"Here’s your {format_type} file with the structure!")

        except Exception as e:
            await update.message.reply_text(f"Error creating structure: {str(e)}")

async def create_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE, text):
    """Create a PDF from text."""
    user_id = update.message.from_user.id
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.multi_cell(0, 10, text)
    pdf_path = os.path.join(UPLOAD_DIR, f"pdf_{user_id}.pdf")
    pdf.output(pdf_path)

    with open(pdf_path, 'rb') as pdf_file:
        await update.message.reply_document(
            document=pdf_file,
            filename=f"output_{user_id}.pdf"
        )

    os.remove(pdf_path)
    await update.message.reply_text("PDF created and sent!")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors gracefully."""
    logger.error(f"Error: {context.error}")
    await update.message.reply_text(
        f"An error occurred: {str(context.error)}. Please try again or contact support."
    )

def main():
    """Set up and run the bot with webhook."""
    app = Application.builder().token(TOKEN).build()

    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("createzip", createzip_command))
    app.add_handler(CommandHandler("quickcreate", quickcreate_command))
    app.add_handler(CommandHandler("createpdf", createpdf_command))
    app.add_handler(CommandHandler("template", template_command))
    app.add_handler(CommandHandler("api", api_command))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Error handler
    app.add_error_handler(error_handler)

    # Set up webhook
    webhook_path = f"/webhook/{TOKEN}"
    full_webhook_url = urljoin(WEBHOOK_URL, webhook_path)
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=webhook_path,
        webhook_url=full_webhook_url
    )
    logger.info(f"Bot connected to Telegram API with webhook at {full_webhook_url}")

if __name__ == "__main__":
    main()
