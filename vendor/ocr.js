const fs = require('node:fs');
const path = require('node:path');
const { createWorker } = require('tesseract.js');

async function main() {
  const images = JSON.parse(fs.readFileSync(0, 'utf8'));
  const langPath = path.join(__dirname, 'tessdata');
  const cachePath = process.env.LEDGER_OCR_CACHE || path.join(__dirname, '..', 'data', 'ocr-cache');
  fs.mkdirSync(cachePath, { recursive: true });
  const worker = await createWorker('eng', 1, {
    langPath,
    cachePath,
    gzip: false,
    logger: () => {},
  });
  const useHsbccolumns = process.env.LEDGER_OCR_HSBC_COLUMNS === '1';
  const dateWorker = useHsbccolumns ? await createWorker('eng', 1, {
    langPath,
    cachePath,
    gzip: false,
    logger: () => {},
  }) : null;
  const pages = [];
  const maxXRatio = Number(process.env.LEDGER_OCR_MAX_X_RATIO || 0.72);
  try {
    for (let i = 0; i < images.length; i += 1) {
      const filename = images[i];
      const header = Buffer.alloc(24);
      const fd = fs.openSync(filename, 'r');
      fs.readSync(fd, header, 0, 24, 0);
      fs.closeSync(fd);
      const width = header.readUInt32BE(16);
      const height = header.readUInt32BE(20);
      const result = await worker.recognize(filename, {}, { blocks: true });
      let dateResult = { data: { blocks: [] } };
      let amountResult = { data: { blocks: [] } };
      if (dateWorker) {
        const dateWidth = Math.max(1, Math.round(width * 0.11));
        const dateTop = Math.round(height * 0.29);
        const dateHeight = Math.round(height * 0.50);
        await dateWorker.setParameters({
          tessedit_char_whitelist: '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ',
          tessedit_pageseg_mode: '6',
        });
        dateResult = await dateWorker.recognize(filename, {
          rectangle: { left: 0, top: dateTop, width: dateWidth, height: dateHeight },
        }, { blocks: true });
        await dateWorker.setParameters({
          tessedit_char_whitelist: '0123456789,.',
          tessedit_pageseg_mode: '6',
        });
        const amountLeft = Math.round(width * 0.55);
        const amountWidth = Math.max(1, Math.round(width * 0.20));
        amountResult = await dateWorker.recognize(filename, {
          rectangle: { left: amountLeft, top: dateTop, width: amountWidth, height: dateHeight },
        }, { blocks: true });
      }
      const lines = [];
      for (const block of result.data.blocks || []) {
        for (const paragraph of block.paragraphs || []) {
          for (const line of paragraph.lines || []) {
            const words = (line.words || [])
            .filter((word) => word.bbox.x0 < width * maxXRatio)
              .sort((a, b) => a.bbox.x0 - b.bbox.x0);
            const text = words.map((word) => word.text).join(' ').replace(/\s+/g, ' ').trim();
            if (text) lines.push({
              text,
              confidence: line.confidence,
              x0: line.bbox.x0,
              y0: line.bbox.y0,
              x1: line.bbox.x1,
              y1: line.bbox.y1,
              words: words.map((word) => ({
                text: word.text,
                confidence: word.confidence,
                x0: word.bbox.x0,
                y0: word.bbox.y0,
                x1: word.bbox.x1,
                y1: word.bbox.y1,
              })),
            });
          }
        }
      }
      const dateWords = [];
      for (const block of dateResult.data.blocks || []) {
        for (const paragraph of block.paragraphs || []) {
          for (const line of paragraph.lines || []) {
            for (const word of line.words || []) {
              const text = String(word.text || '').trim();
              if (text) dateWords.push({
                text,
                confidence: word.confidence,
                x0: word.bbox.x0,
                y0: word.bbox.y0,
                x1: word.bbox.x1,
                y1: word.bbox.y1,
              });
            }
          }
        }
      }
      const amountWords = [];
      for (const block of amountResult.data.blocks || []) {
        for (const paragraph of block.paragraphs || []) {
          for (const line of paragraph.lines || []) {
            for (const word of line.words || []) {
              const text = String(word.text || '').trim();
              if (text) amountWords.push({
                text,
                confidence: word.confidence,
                x0: word.bbox.x0,
                y0: word.bbox.y0,
                x1: word.bbox.x1,
                y1: word.bbox.y1,
              });
            }
          }
        }
      }
      lines.sort((a, b) => (a.y0 - b.y0) || (a.x0 - b.x0));
      pages.push({ page: i + 1, width, height, text: result.data.text || '', lines, date_words: dateWords, amount_words: amountWords });
    }
  } finally {
    await worker.terminate();
    if (dateWorker) await dateWorker.terminate();
  }
  process.stdout.write(JSON.stringify({ pages }));
}

main().catch((error) => {
  process.stderr.write(String(error && error.stack ? error.stack : error));
  process.exitCode = 1;
});
