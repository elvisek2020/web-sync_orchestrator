#!/usr/bin/env node
/**
 * Generuje version.json s aktuální verzí ve formátu v.YYYYMMDD.HHMM
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const now = new Date();
const year = now.getFullYear();
const month = String(now.getMonth() + 1).padStart(2, '0');
const day = String(now.getDate()).padStart(2, '0');
const hours = String(now.getHours()).padStart(2, '0');
const minutes = String(now.getMinutes()).padStart(2, '0');

const version = `v.${year}${month}${day}.${hours}${minutes}`;

const versionData = {
  version: version
};

// V Docker kontextu je WORKDIR /app/ui, takže static adresář je relativně k __dirname
const outputPath = path.join(__dirname, 'static', 'version.json');
const outputDir = path.dirname(outputPath);

try {
  // Vytvořit adresář, pokud neexistuje
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }

  // Zapsat version.json
  fs.writeFileSync(outputPath, JSON.stringify(versionData, null, 2) + '\n');

  console.log(`Generated version: ${version}`);
  console.log(`Written to: ${outputPath}`);
} catch (error) {
  console.error('Error generating version.json:', error);
  console.error('Error details:', error.message);
  console.error('Stack:', error.stack);
  process.exit(1);
}

