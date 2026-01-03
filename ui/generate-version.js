#!/usr/bin/env node
/**
 * Generuje version.json s aktuální verzí ve formátu v.YYYYMMDD.HHMM
 */
const fs = require('fs');
const path = require('path');

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

const outputPath = path.join(__dirname, 'static', 'version.json');
const outputDir = path.dirname(outputPath);

// Vytvořit adresář, pokud neexistuje
if (!fs.existsSync(outputDir)) {
  fs.mkdirSync(outputDir, { recursive: true });
}

// Zapsat version.json
fs.writeFileSync(outputPath, JSON.stringify(versionData, null, 2) + '\n');

console.log(`Generated version: ${version}`);
console.log(`Written to: ${outputPath}`);

