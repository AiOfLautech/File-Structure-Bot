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

# Bot credentials
TOKEN = "7366358800:AAF2684s1_Ipw-4xnazbdU6lXrYHRG0mcnM"
WEBHOOK_URL = "https://file-structure-bot.onrender.com"
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
        "project/bot.py",
        "project/requirements.txt",
        "project/utils/__init__.py"
    ]
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to the File Structure Bot!\n"
        "I can create zipped file structures, convert text to PDF, and more.\n"
        "Commands:\n"
        "/createzip [zip|tar.gz]\n"
        "/quickcreate [zip|tar.gz]\n"
        "/createpdf\n"
        "/template [web|python]\n"
        "/api\n"
        "/help"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Commands:\n"
        "/createzip [zip|tar.gz]\n"
        "/quickcreate [zip|tar.gz]\n"
        "/createpdf\n"
        "/template [web|python]\n"
        "/api\n"
        "/help"
    )

async def createzip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    args = context.args
    fmt = args[0] if args and args[0] in ["zip", "tar.gz"] else "zip"
    user_states[user_id] = {"state": "creating_structure", "format": fmt}
    await update.message.reply_text(
        f"Send a text/JSON file with the file structure (format: {fmt})."
    )

async def quickcreate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    args = context.args
    fmt = args[0] if args and args[0] in ["zip", "tar.gz"] else "zip"
    user_states[user_id] = {"state": "quick_structure", "format": fmt}
    await update.message.reply_text(
        f"Send the structure, one path per line (format: {fmt})."
    )

async def createpdf_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_states[user_id] = {"state": "creating_pdf"}
    await update.message.reply_text("Send text or a file to convert to PDF.")

async def template_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    args = context.args
    name = args[0] if args else None
    if name not in TEMPLATES:
        await update.message.reply_text(f"Invalid. Available: {', '.join(TEMPLATES)}")
        return
    fmt = args[1] if len(args)>1 and args[1] in ["zip","tar.gz"] else "zip"
    await create_structure_with_progress(
        update, context, TEMPLATES[name], fmt, f"{name}_structure"
    )

async def api_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    args = context.args
    if args and args[0] == "test":
        resp = {"Creator":"AI OF LAUTECH","Status":True,"Version":"1.0.0","Timestamp":context.bot.get_timestamp(),"Message":"API test successful!"}
        await update.message.reply_text("\n".join(f"{k}: {v}" for k,v in resp.items()))
    elif args and args[0] == "create_structure" and len(args)>1:
        try:
            data = json.loads(" ".join(args[1:]))
            fmt = data.get("format","zip") if isinstance(data,dict) else "zip"
            paths = data if isinstance(data,list) else data.get("structure",[])
            if not paths: raise ValueError("No structure provided")
            await create_structure_with_progress(
                update, context, [(p["path"],p.get("content","")) for p in paths], fmt, "api_structure"
            )
        except Exception as e:
            await update.message.reply_text(f"API Error: {e}")
    else:
        await update.message.reply_text("Usage: /api [test|create_structure ...]")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    st = user_states.get(user_id,{}).get("state")
    if st not in ["creating_structure","creating_pdf"]:
        await update.message.reply_text("Use /createzip or /createpdf first.")
        return
    file = await update.message.document.get_file()
    fname = update.message.document.file_name
    fpath = os.path.join(UPLOAD_DIR, f"{user_id}_{fname}")
    await file.download_to_drive(fpath)
    try:
        if st == "creating_structure":
            fmt = user_states[user_id]["format"]
            paths = []
            if fname.endswith(".json"):
                with open(fpath) as f: data = json.load(f)
                for itm in data:
                    paths.append((itm["path"], itm.get("content","")))
            else:
                with open(fpath) as f:
                    paths = [(l.strip(),"") for l in f if l.strip()]
            if len(paths)>10:
                user_states[user_id] = {"state":"confirm_structure","format":fmt,"paths":paths}
                summ = "\n".join(p[0] for p in paths[:5])
                if len(paths)>5: summ += f"\n...and {len(paths)-5} more"
                await update.message.reply_text(f"About to create {len(paths)} items:\n{summ}\nReply 'yes' or 'cancel'.")
            else:
                await create_structure_with_progress(update,context,paths,fmt,"structure")
        else:
            with open(fpath) as f: text = f.read()
            await create_pdf(update,context,text)
    finally:
        os.remove(fpath)
        if st != "confirm_structure": user_states[user_id] = None

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    info = user_states.get(user_id,{})
    st = info.get("state")
    txt = update.message.text
    if st == "quick_structure":
        paths = [(l.strip(),"") for l in txt.split("\n") if l.strip()]
        fmt = info.get("format")
        if len(paths)>10:
            user_states[user_id] = {"state":"confirm_structure","format":fmt,"paths":paths}
            summ = "\n".join(p[0] for p in paths[:5])
            if len(paths)>5: summ += f"\n...and {len(paths)-5} more"
            await update.message.reply_text(f"About to create {len(paths)} items:\n{summ}\nReply 'yes' or 'cancel'.")
        else:
            await create_structure_with_progress(update,context,paths,fmt,"structure")
        if st != "confirm_structure": user_states[user_id]=None
    elif st == "creating_pdf":
        await create_pdf(update,context,txt)
        user_states[user_id]=None
    elif st == "confirm_structure":
        if txt.lower() == "yes":
            await create_structure_with_progress(update,context,info["paths"],info["format"],"structure")
        else:
            await update.message.reply_text("Canceled." if txt.lower()=="cancel" else "Reply 'yes' or 'cancel'.")
        user_states[user_id] = None
    else:
        await update.message.reply_text("Use /createzip, /quickcreate, or /createpdf.")

async def create_structure_with_progress(update: Update, context: ContextTypes.DEFAULT_TYPE, paths, fmt, out):
    uid = update.message.from_user.id
    total = len(paths)
    with tempfile.TemporaryDirectory() as td:
        for i,(p,c) in enumerate(paths,1):
            fp = os.path.normpath(os.path.join(td,p.lstrip('/')))
            if not fp.startswith(td): continue
            if p.endswith('/'): os.makedirs(fp,exist_ok=True)
            else:
                os.makedirs(os.path.dirname(fp),exist_ok=True)
                with open(fp,'w') as f: f.write(c)
            if i%5==0 or i==total:
                await update.message.reply_text(f"Creating item {i}/{total}...")
        zp = os.path.join(ZIP_DIR,f"{out}_{uid}")
        if fmt=="zip":
            shutil.make_archive(zp,'zip',td); af = f"{zp}.zip"
        else:
            af = f"{zp}.tar.gz"
            with tarfile.open(af,"w:gz") as tar: tar.add(td,arcname="")
        with open(af,'rb') as afile:
            await update.message.reply_document(document=afile,filename=f"{out}.{fmt.replace('.','')}")
        os.remove(af)
        await update.message.reply_text(f"Here’s your {fmt} file!")

async def create_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE, text):
    uid = update.message.from_user.id
    pdf = FPDF(); pdf.add_page(); pdf.set_font("Arial", size=12); pdf.multi_cell(0,10,text)
    ppath = os.path.join(UPLOAD_DIR,f"pdf_{uid}.pdf"); pdf.output(ppath)
    with open(ppath,'rb') as pf: await update.message.reply_document(document=pf,filename=f"output_{uid}.pdf")
    os.remove(ppath); await update.message.reply_text("PDF sent!")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(context.error)
    await update.message.reply_text(f"Error: {context.error}")

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    # handlers... same as above
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("createzip", createzip_command))
    app.add_handler(CommandHandler("quickcreate", quickcreate_command))
    app.add_handler(CommandHandler("createpdf", createpdf_command))
    app.add_handler(CommandHandler("template", template_command))
    app.add_handler(CommandHandler("api", api_command))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)
    path = f"/webhook/{TOKEN}"
    url = urljoin(WEBHOOK_URL, path)
    app.run_webhook(listen="0.0.0.0", port=PORT, url_path=path, webhook_url=url)
    logger.info(f"Webhook at {url}")
