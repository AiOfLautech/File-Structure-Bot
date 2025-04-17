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
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot credentials (hard‑coded or via env)
TOKEN = os.getenv("TOKEN", "7366358800:AAF2684s1_Ipw-4xnazbdU6lXrYHRG0mcnM")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://file-structure-bot.onrender.com")
PORT = int(os.getenv("PORT", 8443))

# Ensure directories
UPLOAD_DIR = "uploads"
ZIP_DIR = "zips"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(ZIP_DIR, exist_ok=True)

# In-memory state
user_states = {}

# Templates
TEMPLATES = {
    "web": ["project/", "project/index.html", "project/css/style.css", "project/js/script.js"],
    "python": ["project/", "project/bot.py", "project/requirements.txt", "project/utils/__init__.py"]
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to the File Structure Bot!\n"
        "Use /createzip, /quickcreate, /createpdf, /template, /api, /help."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Commands:\n"
        "/createzip [zip|tar.gz]\n"
        "/quickcreate [zip|tar.gz]\n"
        "/createpdf\n"
        "/template [web|python]\n"
        "/api test\n"
        "/api create_structure [json]\n"
        "/help"
    )

# Utility: create archive
async def create_archive(update, context, paths, fmt, name):
    uid = update.effective_user.id
    total = len(paths)
    with tempfile.TemporaryDirectory() as tmpdir:
        for i, (p, content) in enumerate(paths, 1):
            full = os.path.join(tmpdir, p.lstrip('/'))
            if p.endswith('/'):
                os.makedirs(full, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, 'w') as f:
                    f.write(content)
            if i % 5 == 0 or i == total:
                await update.message.reply_text(f"Creating {i}/{total}...")
        out_base = os.path.join(ZIP_DIR, f"{name}_{uid}")
        if fmt == 'zip':
            shutil.make_archive(out_base, 'zip', tmpdir)
            archive = f"{out_base}.zip"
        else:
            archive = f"{out_base}.tar.gz"
            with tarfile.open(archive, 'w:gz') as tar:
                tar.add(tmpdir, arcname='')
        with open(archive, 'rb') as af:
            await update.message.reply_document(af, filename=os.path.basename(archive))
        os.remove(archive)
        await update.message.reply_text(f"Here’s your {fmt} archive!")

# Utility: create PDF
async def create_pdf(update, context, text):
    uid = update.effective_user.id
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font('Arial', size=12)
    pdf.multi_cell(0, 10, text)
    pdf_path = os.path.join(UPLOAD_DIR, f"{uid}.pdf")
    pdf.output(pdf_path)
    with open(pdf_path, 'rb') as pf:
        await update.message.reply_document(pf, filename=f"pdf_{uid}.pdf")
    os.remove(pdf_path)
    await update.message.reply_text("PDF created!")

async def handle_document(update, context):
    uid = update.effective_user.id
    state = user_states.get(uid)
    if not state:
        return await update.message.reply_text("Use /createzip or /createpdf first.")
    file = await update.message.document.get_file()
    dest = os.path.join(UPLOAD_DIR, f"{uid}_{update.message.document.file_name}")
    await file.download_to_drive(dest)
    if state['action'] == 'zip':
        if dest.endswith('.json'):
            data = json.load(open(dest))
            paths = [(i['path'], i.get('content','')) for i in data]
        else:
            lines = open(dest).read().splitlines()
            paths = [(l,'') for l in lines if l]
        await create_archive(update, context, paths, state['format'], 'structure')
    else:
        text = open(dest).read()
        await create_pdf(update, context, text)
    os.remove(dest)
    user_states.pop(uid, None)

async def handle_text(update, context):
    uid = update.effective_user.id
    state = user_states.get(uid)
    text = update.message.text
    if state and state['action'] == 'quickzip':
        paths = [(l,'') for l in text.splitlines() if l]
        await create_archive(update, context, paths, state['format'], 'structure')
        user_states.pop(uid, None)
    elif state and state['action'] == 'pdf':
        await create_pdf(update, context, text)
        user_states.pop(uid, None)
    elif state and 'confirm' in state:
        if text.lower()=='yes':
            await create_archive(update, context, state['confirm'], state['format'], 'structure')
        else:
            await update.message.reply_text('Canceled.')
        user_states.pop(uid, None)
    else:
        await update.message.reply_text('Use /createzip, /quickcreate, or /createpdf.')

# Commands
async def start_cmd(update, context): return await start(update, context)
async def help_cmd(update, context): return await help_command(update, context)

async def createzip_cmd(update, context):
    uid = update.effective_user.id
    fmt = context.args[0] if context.args and context.args[0] in ['zip','tar.gz'] else 'zip'
    user_states[uid] = {'action':'zip','format':fmt}
    await update.message.reply_text(f"Send a file structure text/JSON (format {fmt}).")

async def quickcreate_cmd(update, context):
    uid = update.effective_user.id
    fmt = context.args[0] if context.args and context.args[0] in ['zip','tar.gz'] else 'zip'
    user_states[uid] = {'action':'quickzip','format':fmt}
    await update.message.reply_text(f"Send structure lines (format {fmt}).")

async def createpdf_cmd(update, context):
    uid = update.effective_user.id
    user_states[uid] = {'action':'pdf'}
    await update.message.reply_text('Send text or upload a text file to convert.')

async def template_cmd(update, context):
    key = context.args[0] if context.args else None
    fmt = context.args[1] if len(context.args)>1 and context.args[1] in ['zip','tar.gz'] else 'zip'
    if key not in TEMPLATES:
        return await update.message.reply_text(f"Invalid template: {', '.join(TEMPLATES)}")
    await create_archive(update, context, [(p,'') for p in TEMPLATES[key]], fmt, f"{key}_template")

async def api_cmd(update, context):
    if context.args and context.args[0]=='test':
        return await update.message.reply_text(json.dumps({'Creator':'AI OF LAUTECH','Status':True,'Version':'1.0.0','Timestamp':int(json.loads('{}')), 'Message':'OK'}))
    if context.args and context.args[0]=='create_structure':
        try:
            data = json.loads(' '.join(context.args[1:]))
            fmt = data.get('format','zip') if isinstance(data,dict) else 'zip'
            arr = [(i['path'],i.get('content','')) for i in (data.get('structure') if isinstance(data,dict) else data)]
            return await create_archive(update, context, arr, fmt, 'api')
        except Exception as e:
            return await update.message.reply_text(f"Error: {e}")
    return await update.message.reply_text('Usage: /api test | /api create_structure [...])')

# Bot setup
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler('start', start_cmd))
app.add_handler(CommandHandler('help', help_cmd))
app.add_handler(CommandHandler('createzip', createzip_cmd))
app.add_handler(CommandHandler('quickcreate', quickcreate_cmd))
app.add_handler(CommandHandler('createpdf', createpdf_cmd))
app.add_handler(CommandHandler('template', template_cmd))
app.add_handler(CommandHandler('api', api_cmd))
app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
app.run_webhook(listen='0.0.0.0', port=PORT, url_path=f"/webhook/{TOKEN}", webhook_url=urljoin(WEBHOOK_URL, f"/webhook/{TOKEN}"))
