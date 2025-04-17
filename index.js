// Load dependencies
const { Telegraf } = require('telegraf');
const express = require('express');
const fs = require('fs-extra');
const path = require('path');
const archiver = require('archiver');
const PDFDocument = require('pdfkit');
const axios = require('axios');

// Configuration
const TOKEN = process.env.TOKEN || '7366358800:AAF2684s1_Ipw-4xnazbdU6lXrYHRG0mcnM';
const WEBHOOK_URL = process.env.WEBHOOK_URL || 'https://file-structure-bot.onrender.com';
const PORT = process.env.PORT || 8443;

// Ensure working directories exist
const UPLOAD_DIR = path.join(__dirname, 'uploads');
const ZIP_DIR = path.join(__dirname, 'zips');
fs.ensureDirSync(UPLOAD_DIR);
fs.ensureDirSync(ZIP_DIR);

// In-memory user state map
const userStates = new Map();

// Predefined templates
const TEMPLATES = {
  web: [
    'project/',
    'project/index.html',
    'project/css/style.css',
    'project/js/script.js'
  ],
  python: [
    'project/',
    'project/index.py',
    'project/requirements.txt',
    'project/utils/__init__.py'
  ]
};

// Initialize bot
const bot = new Telegraf(TOKEN);

// /start and /help
bot.start(ctx => ctx.reply(
  `Welcome! I create file structures and PDFs.
Commands:
/createzip [zip|tar.gz]
/quickcreate [zip|tar.gz]
/createpdf
/template [web|python]
/api test
/api create_structure [json]
`
));
bot.help(ctx => ctx.reply('Use /start to see all commands.'));

// UTIL: download file from Telegram
async function downloadFile(ctx, fileId, dest) {
  const link = await ctx.telegram.getFileLink(fileId);
  const response = await axios.get(link.href, { responseType: 'stream' });
  const writer = fs.createWriteStream(dest);
  return new Promise((resolve, reject) => {
    response.data.pipe(writer);
    writer.on('finish', resolve);
    writer.on('error', reject);
  });
}

// UTIL: create structure archive
async function createArchive(ctx, paths, format, outputName) {
  const total = paths.length;
  const tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), 'fsbot-'));
  try {
    for (let i = 0; i < paths.length; i++) {
      const [p, content] = paths[i];
      const fullPath = path.join(tmpDir, p);
      if (p.endsWith('/')) {
        await fs.ensureDir(fullPath);
      } else {
        await fs.ensureDir(path.dirname(fullPath));
        await fs.writeFile(fullPath, content || '');
      }
      if ((i+1) % 5 === 0 || i+1 === total) {
        await ctx.reply(`Creating item ${i+1}/${total}...`);
      }
    }
    const archivePath = path.join(ZIP_DIR, `${outputName}_${ctx.from.id}` + (format === 'zip' ? '.zip' : '.tar.gz'));
    const output = fs.createWriteStream(archivePath);
    const archive = archiver(format === 'zip' ? 'zip' : 'tar', format === 'tar.gz' ? { gzip: true } : {});
    archive.pipe(output);
    archive.directory(tmpDir, false);
    await archive.finalize();
    await output.on('close', () => {});
    await ctx.replyWithDocument({ source: archivePath, filename: path.basename(archivePath) });
    await fs.remove(archivePath);
  } catch (err) {
    await ctx.reply(`Error: ${err.message}`);
  } finally {
    await fs.remove(tmpDir);
  }
}

// UTIL: create PDF
async function createPDF(ctx, text) {
  const doc = new PDFDocument();
  const pdfPath = path.join(UPLOAD_DIR, `pdf_${ctx.from.id}.pdf`);
  doc.pipe(fs.createWriteStream(pdfPath));
  doc.font('Times-Roman').fontSize(12).text(text);
  doc.end();
  await new Promise(r => doc.on('end', r));
  await ctx.replyWithDocument({ source: pdfPath, filename: `output_${ctx.from.id}.pdf` });
  await fs.remove(pdfPath);
}

// COMMAND: /createzip
bot.command('createzip', ctx => {
  const args = ctx.message.text.split(' ').slice(1);
  const fmt = args[0] === 'tar.gz' ? 'tar.gz' : 'zip';
  userStates.set(ctx.from.id, { state: 'creating_structure', format: fmt });
  ctx.reply(`Send me a text or JSON file describing the structure (format: ${fmt}).`);
});

// COMMAND: /quickcreate
bot.command('quickcreate', ctx => {
  const args = ctx.message.text.split(' ').slice(1);
  const fmt = args[0] === 'tar.gz' ? 'tar.gz' : 'zip';
  userStates.set(ctx.from.id, { state: 'quick_structure', format: fmt });
  ctx.reply(`Send me the structure, one path per line (format: ${fmt}).`);
});

// COMMAND: /createpdf
bot.command('createpdf', ctx => {
  userStates.set(ctx.from.id, { state: 'creating_pdf' });
  ctx.reply('Send me text or a text file to convert into PDF.');
});

// COMMAND: /template
bot.command('template', ctx => {
  const parts = ctx.message.text.split(' ');
  const name = parts[1];
  const fmt = parts[2] === 'tar.gz' ? 'tar.gz' : 'zip';
  if (!TEMPLATES[name]) return ctx.reply(`Invalid template. Choose: ${Object.keys(TEMPLATES).join(', ')}`);
  createArchive(ctx, TEMPLATES[name].map(p => [p, '']), fmt, `${name}_structure`);
});

// COMMAND: /api
overlay
bot.command('api', async ctx => {
  const parts = ctx.message.text.split(' ');
  const cmd = parts[1];
  if (cmd === 'test') {
    return ctx.reply(JSON.stringify({ Creator: 'AI OF LAUTECH', Status: true, Version: '1.0.0', Timestamp: Date.now(), Message: 'API test successful!' }, null, 2));
  }
  if (cmd === 'create_structure') {
    try {
      const data = JSON.parse(parts.slice(2).join(' '));
      const fmt = data.format === 'tar.gz' ? 'tar.gz' : 'zip';
      const paths = Array.isArray(data.structure) ? data.structure : data;
      const arr = paths.map(p => [p.path, p.content || '']);
      return createArchive(ctx, arr, fmt, 'api_structure');
    } catch (e) {
      return ctx.reply(`API error: ${e.message}`);
    }
  }
  ctx.reply('Usage: /api test OR /api create_structure [{...}]');
});

// HANDLER: documents
bot.on('document', async ctx => {
  const state = userStates.get(ctx.from.id);
  if (!state) return ctx.reply('Use /createzip or /createpdf first.');

  const dest = path.join(UPLOAD_DIR, `${ctx.from.id}_${ctx.message.document.file_name}`);
  await downloadFile(ctx, ctx.message.document.file_id, dest);

  if (state.state === 'creating_structure') {
    let paths = [];
    if (dest.endsWith('.json')) {
      const data = await fs.readJson(dest);
      paths = data.map(item => [item.path, item.content || '']);
    } else {
      const lines = (await fs.readFile(dest, 'utf8')).split('\n');
      paths = lines.filter(l => l.trim()).map(l => [l.trim(), '']);
    }
    if (paths.length > 10) {
      userStates.set(ctx.from.id, { ...state, confirm: paths });
      return ctx.reply(`Confirm creating ${paths.length} items? Reply 'yes' to proceed.`);
    }
    await createArchive(ctx, paths, state.format, 'structure');
  } else if (state.state === 'creating_pdf') {
    const text = await fs.readFile(dest, 'utf8');
    await createPDF(ctx, text);
  }
  userStates.delete(ctx.from.id);
  await fs.remove(dest);
});

// HANDLER: text replies
bot.on('text', async ctx => {
  const state = userStates.get(ctx.from.id);
  const text = ctx.message.text;
  if (!state) return;

  if (state.state === 'quick_structure') {
    const paths = text.split('\n').filter(l => l.trim()).map(l => [l.trim(), '']);
    if (paths.length > 10) {
      userStates.set(ctx.from.id, { ...state, confirm: paths });
      return ctx.reply(`Confirm creating ${paths.length} items? Reply 'yes'.`);
    }
    await createArchive(ctx, paths, state.format, 'structure');
  } else if (state.state === 'creating_pdf') {
    await createPDF(ctx, text);
  } else if (state.confirm) {
    if (text.toLowerCase() === 'yes') {
      await createArchive(ctx, state.confirm, state.format, 'structure');
    } else {
      await ctx.reply('Canceled.');
    }
  }
  userStates.delete(ctx.from.id);
});

// Start Express & webhook
const app = express();
app.use(bot.webhookCallback(`/webhook/${TOKEN}`));
bot.telegram.setWebhook(`${WEBHOOK_URL}/webhook/${TOKEN}`);
app.listen(PORT, () => console.log(`Listening on ${PORT}`));
