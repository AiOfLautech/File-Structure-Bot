// Load dependencies
const { Telegraf } = require('telegraf');
const express = require('express');
const fs = require('fs-extra');
const path = require('path');
const os = require('os');
const archiver = require('archiver');
const PDFDocument = require('pdfkit');
const axios = require('axios');

// Config
const TOKEN = process.env.TOKEN || '7366358800:AAF2684s1_Ipw-4xnazbdU6lXrYHRG0mcnM';
const WEBHOOK_URL = process.env.WEBHOOK_URL || 'https://file-structure-bot.onrender.com';
const PORT = process.env.PORT || 8443;

// Ensure directories
const UPLOAD_DIR = path.join(__dirname, 'uploads');
const ZIP_DIR = path.join(__dirname, 'zips');
fs.ensureDirSync(UPLOAD_DIR);
fs.ensureDirSync(ZIP_DIR);

// In-memory state
const userStates = new Map();

// Templates
const TEMPLATES = {
  web: ['project/', 'project/index.html', 'project/css/style.css', 'project/js/script.js'],
  python: ['project/', 'project/index.py', 'project/requirements.txt', 'project/utils/__init__.py']
};

// Init bot
const bot = new Telegraf(TOKEN);

// /start & /help
bot.start(ctx => ctx.reply(`Welcome! Available commands:
/createzip [zip|tar.gz]
/quickcreate [zip|tar.gz]
/createpdf
/template [web|python]
/api test
/api create_structure [json]`));
bot.help(ctx => ctx.reply('Send /start to see commands.'));

// Download helper
async function downloadFile(ctx, fileId, dest) {
  const link = await ctx.telegram.getFileLink(fileId);
  const response = await axios.get(link.href, { responseType: 'stream' });
  const stream = fs.createWriteStream(dest);
  return new Promise((res, rej) => {
    response.data.pipe(stream);
    stream.on('finish', res);
    stream.on('error', rej);
  });
}

// Archive helper
async function createArchive(ctx, paths, fmt, name) {
  const uid = ctx.from.id;
  const total = paths.length;
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'fsbot-'));
  try {
    for (let i = 0; i < total; i++) {
      const [p, content] = paths[i];
      const full = path.join(tempDir, p);
      if (p.endsWith('/')) await fs.ensureDir(full);
      else {
        await fs.ensureDir(path.dirname(full));
        await fs.writeFile(full, content || '');
      }
      if ((i + 1) % 5 === 0 || i + 1 === total) {
        await ctx.reply(`Creating ${i+1}/${total}...`);
      }
    }
    const outPath = path.join(ZIP_DIR, `${name}_${uid}.${fmt === 'zip' ? 'zip' : 'tar.gz'}`);
    const outStream = fs.createWriteStream(outPath);
    const archive = archiver(fmt === 'zip' ? 'zip' : 'tar', fmt === 'tar.gz' ? { gzip: true } : {});
    archive.pipe(outStream);
    archive.directory(tempDir, false);
    await archive.finalize();
    await new Promise(r => outStream.on('close', r));
    await ctx.replyWithDocument({ source: outPath, filename: path.basename(outPath) });
    await fs.remove(outPath);
  } catch (err) {
    await ctx.reply(`Error: ${err.message}`);
  } finally {
    await fs.remove(tempDir);
  }
}

// PDF helper
async function createPDF(ctx, text) {
  const uid = ctx.from.id;
  const pdf = new PDFDocument();
  const pdfPath = path.join(UPLOAD_DIR, `pdf_${uid}.pdf`);
  pdf.pipe(fs.createWriteStream(pdfPath));
  pdf.font('Times-Roman').fontSize(12).text(text);
  pdf.end();
  await new Promise(r => pdf.on('end', r));
  await ctx.replyWithDocument({ source: pdfPath, filename: `output_${uid}.pdf` });
  await fs.remove(pdfPath);
}

// Commands
bot.command('createzip', ctx => {
  const fmt = ctx.message.text.split(' ')[1] === 'tar.gz' ? 'tar.gz' : 'zip';
  userStates.set(ctx.from.id, { action: 'zip', fmt });
  ctx.reply(`Send a structure file (format ${fmt}).`);
});
bot.command('quickcreate', ctx => {
  const fmt = ctx.message.text.split(' ')[1] === 'tar.gz' ? 'tar.gz' : 'zip';
  userStates.set(ctx.from.id, { action: 'quick', fmt });
  ctx.reply(`Send structure lines (format ${fmt}).`);
});
bot.command('createpdf', ctx => {
  userStates.set(ctx.from.id, { action: 'pdf' });
  ctx.reply('Send text or upload file for PDF.');
});
bot.command('template', ctx => {
  const [ , key, fmtArg ] = ctx.message.text.split(' ');
  const fmt = fmtArg === 'tar.gz' ? 'tar.gz' : 'zip';
  if (!TEMPLATES[key]) return ctx.reply(`Invalid: ${Object.keys(TEMPLATES).join(', ')}`);
  createArchive(ctx, TEMPLATES[key].map(p => [p, '']), fmt, `${key}_tpl`);
});
bot.command('api', async ctx => {
  const parts = ctx.message.text.split(' ');
  if (parts[1] === 'test') return ctx.reply(JSON.stringify({ Creator: 'AI OF LAUTECH', Status: true, Version: '1.0.0', Timestamp: Date.now(), Message: 'OK' }, null, 2));
  if (parts[1] === 'create_structure') {
    try {
      const data = JSON.parse(parts.slice(2).join(' '));
      const fmt = data.format === 'tar.gz' ? 'tar.gz' : 'zip';
      const arr = (data.structure || data).map(item => [item.path, item.content || '']);
      return createArchive(ctx, arr, fmt, 'api');
    } catch (e) {
      return ctx.reply(`API error: ${e.message}`);
    }
  }
  ctx.reply('Usage: /api test OR /api create_structure [json]');
});

// Handlers
bot.on('document', async ctx => {
  const state = userStates.get(ctx.from.id);
  if (!state) return ctx.reply('Use /createzip or /createpdf first.');
  const dest = path.join(UPLOAD_DIR, `${ctx.from.id}_${ctx.message.document.file_name}`);
  await downloadFile(ctx, ctx.message.document.file_id, dest);
  if (state.action === 'zip') {
    const ext = path.extname(dest);
    let paths;
    if (ext === '.json') paths = (await fs.readJson(dest)).map(i => [i.path, i.content || '']);
    else paths = (await fs.readFile(dest, 'utf8')).split('\n').filter(l => l).map(l => [l, '']);
    await createArchive(ctx, paths, state.fmt, 'structure');
  } else if (state.action === 'pdf') {
    const txt = await fs.readFile(dest, 'utf8');
    await createPDF(ctx, txt);
  }
  userStates.delete(ctx.from.id);
  await fs.remove(dest);
});

bot.on('text', async ctx => {
  const state = userStates.get(ctx.from.id);
  if (!state) return;
  if (state.action === 'quick') {
    const paths = ctx.message.text.split('\n').filter(l => l).map(l => [l, '']);
    await createArchive(ctx, paths, state.fmt, 'structure');
  } else if (state.action === 'pdf') {
    await createPDF(ctx, ctx.message.text);
  }
  userStates.delete(ctx.from.id);
});

// Express & webhook
const app = express();
app.use(bot.webhookCallback(`/webhook/${TOKEN}`));
bot.telegram.setWebhook(`${WEBHOOK_URL}/webhook/${TOKEN}`);
app.listen(PORT, () => console.log(`Listening on ${PORT}`));
