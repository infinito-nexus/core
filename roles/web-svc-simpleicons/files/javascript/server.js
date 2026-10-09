// nocheck: mirrored-unit-test - a standalone Express server whose module body binds a port and reads the container environment at import
import express from 'express';
import * as icons from 'simple-icons';
import sharp from 'sharp';

const app = express();
const port = Number(process.env.PORT);
const docsUrl = process.env.DOCS_URL;
const organization = process.env.ORGANIZATION;

function getExportName(slug) {
  const name = slug
    .split('-')
    .map(part => part[0].toUpperCase() + part.slice(1))
    .join('');
  return `si${name}`;
}

app.get('/', (req, res) => {
  if (docsUrl) {
    return res.redirect(docsUrl);
  }
  res
    .status(200)
    .type('text/plain; charset=utf-8')
    .send(`simpleicons.org\nprovided by ${organization}\n`);
});

app.get('/:slug.svg', (req, res) => {
  const slug = req.params.slug.toLowerCase();
  const exportName = getExportName(slug);
  const icon = icons[exportName];

  if (!icon) {
    return res.status(404).send('Icon not found');
  }

  res.type('image/svg+xml');
  res.send(icon.svg);
});

app.get('/:slug.png', async (req, res) => {
  const slug = req.params.slug.toLowerCase();
  const size = parseInt(req.query.size, 10) || 128;
  const exportName = getExportName(slug);
  const icon = icons[exportName];

  if (!icon) {
    return res.status(404).send('Icon not found');
  }

  try {
    const pngBuffer = await sharp(Buffer.from(icon.svg))
      .resize(size, size)
      .png()
      .toBuffer();

    res.type('image/png');
    res.send(pngBuffer);
  } catch (err) {
    console.error('PNG generation error:', err);
    res.status(500).send('PNG generation error');
  }
});

app.listen(port, () => {
  console.log(`Simple-Icons server listening at http://0.0.0.0:${port}`);
});
