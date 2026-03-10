import fs from "node:fs/promises";
import path from "node:path";
import PptxGenJS from "pptxgenjs";

const COLORS = {
  canvas: "F4F7FB",
  panel: "FFFFFF",
  border: "D9E2EC",
  title: "10233F",
  body: "1F2A44",
  muted: "677489",
  accent: "0F766E",
  accentSoft: "DFF5F0",
  footer: "5B6478",
};

const HEADER_LABEL = "\u4E1A\u52A1\u6C47\u62A5\uFF5C\u590D\u6742\u8DEF\u53E3\u53EF\u4FE1\u8FDE\u63A5";
const PANEL_LABEL = "\u6838\u5FC3\u8981\u70B9";

function parseArgs(argv) {
  const args = new Map();
  for (let index = 2; index < argv.length; index += 1) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key.startsWith("--") || value === undefined) {
      throw new Error(`Invalid argument near: ${key ?? "<end>"}`);
    }
    args.set(key.slice(2), value);
    index += 1;
  }
  return args;
}

function parseOutline(markdown) {
  const slides = [];
  let current = null;
  for (const rawLine of markdown.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) {
      continue;
    }
    const titleMatch = line.match(/^##\s+(P\d+\uFF5C.+)$/u);
    if (titleMatch) {
      current = { title: titleMatch[1], bullets: [] };
      slides.push(current);
      continue;
    }
    const bulletMatch = line.match(/^- (.+)$/);
    if (bulletMatch && current) {
      current.bullets.push(bulletMatch[1]);
    }
  }
  if (slides.length === 0) {
    throw new Error("No slides found in outline.");
  }
  return slides;
}

function addChainDiagram(slide, pptx, fontFace) {
  const nodes = [
    { x: 1.02, title: "T06", subtitle: "\u4FEE\u8F93\u5165" },
    { x: 4.02, title: "T04", subtitle: "\u5B9A\u8FB9\u754C" },
    { x: 7.02, title: "T05", subtitle: "\u51FA\u62D3\u6251\u53EF\u62D2\u7EDD" },
  ];

  for (const node of nodes) {
    slide.addShape(pptx.ShapeType.roundRect, {
      x: node.x,
      y: 2.2,
      w: 2.15,
      h: 0.74,
      line: { color: COLORS.border, width: 1 },
      fill: { color: "F9FBFD" },
    });
    slide.addText(node.title, {
      x: node.x + 0.18,
      y: 2.32,
      w: 0.5,
      h: 0.18,
      fontFace,
      fontSize: 14,
      bold: true,
      color: COLORS.accent,
      margin: 0,
    });
    slide.addText(node.subtitle, {
      x: node.x + 0.18,
      y: 2.54,
      w: 1.7,
      h: 0.18,
      fontFace,
      fontSize: 10,
      color: COLORS.body,
      margin: 0,
    });
  }

  slide.addShape(pptx.ShapeType.chevron, {
    x: 3.28,
    y: 2.39,
    w: 0.42,
    h: 0.34,
    line: { color: COLORS.accent, transparency: 100 },
    fill: { color: COLORS.accentSoft },
  });
  slide.addShape(pptx.ShapeType.chevron, {
    x: 6.28,
    y: 2.39,
    w: 0.42,
    h: 0.34,
    line: { color: COLORS.accent, transparency: 100 },
    fill: { color: COLORS.accentSoft },
  });
}

function pickBulletMetrics(bullets) {
  const longest = Math.max(...bullets.map((item) => item.length));
  if (bullets.length >= 5 || longest > 34) {
    return { fontSize: 17, boxHeight: 0.68, gap: 0.76 };
  }
  return { fontSize: 18, boxHeight: 0.7, gap: 0.85 };
}

function addFrame(slide, pptx, title, pageLabel, fontFace) {
  slide.background = { color: COLORS.canvas };
  slide.addShape(pptx.ShapeType.rect, {
    x: 0,
    y: 0,
    w: 13.333,
    h: 0.28,
    line: { color: COLORS.accent, transparency: 100 },
    fill: { color: COLORS.accent },
  });
  slide.addText(HEADER_LABEL, {
    x: 0.72,
    y: 0.46,
    w: 5.7,
    h: 0.28,
    fontFace,
    fontSize: 9,
    color: COLORS.muted,
    margin: 0,
  });
  slide.addText(title, {
    x: 0.72,
    y: 0.78,
    w: 11.3,
    h: 0.6,
    fontFace,
    fontSize: 24,
    bold: true,
    color: COLORS.title,
    margin: 0,
  });
  slide.addShape(pptx.ShapeType.roundRect, {
    x: 0.72,
    y: 1.55,
    w: 11.92,
    h: 5.38,
    rectRadius: 0.08,
    line: { color: COLORS.border, width: 1 },
    fill: { color: COLORS.panel },
  });
  slide.addShape(pptx.ShapeType.rect, {
    x: 0.98,
    y: 1.86,
    w: 1.38,
    h: 0.28,
    line: { color: COLORS.accentSoft, transparency: 100 },
    fill: { color: COLORS.accentSoft },
  });
  slide.addText(PANEL_LABEL, {
    x: 1.12,
    y: 1.9,
    w: 1.15,
    h: 0.18,
    fontFace,
    fontSize: 9,
    bold: true,
    color: COLORS.accent,
    margin: 0,
  });
  slide.addText(pageLabel, {
    x: 11.78,
    y: 7.08,
    w: 0.8,
    h: 0.2,
    align: "right",
    fontFace,
    fontSize: 9,
    color: COLORS.footer,
    margin: 0,
  });
}

function addBullets(slide, pptx, bullets, fontFace, startY = 2.32) {
  const { fontSize, boxHeight, gap } = pickBulletMetrics(bullets);
  let currentY = startY;
  for (const bullet of bullets) {
    slide.addShape(pptx.ShapeType.ellipse, {
      x: 1.08,
      y: currentY + 0.18,
      w: 0.14,
      h: 0.14,
      line: { color: COLORS.accent, transparency: 100 },
      fill: { color: COLORS.accent },
    });
    slide.addText(bullet, {
      x: 1.34,
      y: currentY,
      w: 10.86,
      h: boxHeight,
      margin: 0,
      valign: "mid",
      fontFace,
      fontSize,
      color: COLORS.body,
    });
    currentY += gap;
  }
}

async function writeDeck(slides, outPath, fontFace, addFirstSlideDiagram) {
  const pptx = new PptxGenJS();
  pptx.layout = "LAYOUT_WIDE";
  pptx.author = "OpenAI Codex";
  pptx.company = "OpenAI Codex";
  pptx.subject = "T06 T04 T05 business briefing";
  pptx.title = slides[0].title;
  pptx.lang = "zh-CN";
  pptx.theme = {
    headFontFace: fontFace,
    bodyFontFace: fontFace,
    lang: "zh-CN",
  };

  slides.forEach((slideDef, index) => {
    const slide = pptx.addSlide();
    addFrame(slide, pptx, slideDef.title, `${index + 1} / ${slides.length}`, fontFace);
    if (addFirstSlideDiagram && index === 0) {
      addChainDiagram(slide, pptx, fontFace);
      addBullets(slide, pptx, slideDef.bullets, fontFace, 3.18);
    } else {
      addBullets(slide, pptx, slideDef.bullets, fontFace);
    }
  });

  await fs.mkdir(path.dirname(outPath), { recursive: true });
  await pptx.writeFile({ fileName: outPath });
}

async function main() {
  const args = parseArgs(process.argv);
  const briefOutline = args.get("brief-outline");
  const detailedOutline = args.get("detailed-outline");
  const outdir = args.get("outdir");
  const briefOutput = args.get("brief-output") ?? "T06_T04_T05_BRIEF.pptx";
  const detailedOutput = args.get("detailed-output") ?? "T06_T04_T05_DETAILED.pptx";
  const fontFace = args.get("font-face") ?? "Noto Sans SC";

  if (!briefOutline || !detailedOutline || !outdir) {
    throw new Error(
      "Usage: node generate_decks.mjs --brief-outline <file> --detailed-outline <file> --outdir <dir> [--font-face <font>]"
    );
  }

  const [briefMd, detailedMd] = await Promise.all([
    fs.readFile(briefOutline, "utf8"),
    fs.readFile(detailedOutline, "utf8"),
  ]);

  const briefSlides = parseOutline(briefMd);
  const detailedSlides = parseOutline(detailedMd);

  await writeDeck(briefSlides, path.join(outdir, briefOutput), fontFace, true);
  await writeDeck(
    detailedSlides,
    path.join(outdir, detailedOutput),
    fontFace,
    true
  );
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
