#!/usr/bin/env node

const nunjucks = require('nunjucks');
const fs = require('fs');
const path = require('path');

// Configure Nunjucks
const env = nunjucks.configure('src/templates', {
    autoescape: true,
    trimBlocks: true,
    lstripBlocks: true,
});

// Render the template
const html = env.render('index.jinja', {
    title: 'Lablet Controller',
    serviceName: 'lablet-controller',
    serviceEmoji: '🎛️',
    themeColor: '#2ecc71',
});

// Write to src/tmp_build/index.html for Parcel to process
const buildDir = path.join(__dirname, 'src', 'tmp_build');
if (!fs.existsSync(buildDir)) {
    fs.mkdirSync(buildDir, { recursive: true });
}
const outputPath = path.join(buildDir, 'index.html');
fs.writeFileSync(outputPath, html);

console.log('✓ Template rendered successfully to src/tmp_build/index.html');
