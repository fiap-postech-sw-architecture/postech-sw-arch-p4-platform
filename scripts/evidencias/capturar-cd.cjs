// Grafo do CD de um run do GitHub Actions, da página pública (sem login), recortado ao grafo.
//
// Uso: PLAYWRIGHT_CORE=<pasta do playwright-core> node scripts/evidencias/capturar-cd.cjs <url do run> <saida.png> [escala]
//
// Chrome instalado, sem interface, viewport de 1.400 px, tema claro e UTC, como nas outras capturas do
// registro. O recorte é a união dos cartões e dos conectores do grafo, com 12 px de folga, e a escala
// padrão é 2: a letra dos nós, de 8 px na página do GitHub, só se lê no PDF com a imagem na largura
// de uma página paisagem. Só leitura: nada é clicado, e o run recém-terminado nunca fica `networkidle`,
// então o script espera o grafo, não a rede. Depois, a paleta de 128 cores (README das evidências).
const { chromium } = require(process.env.PLAYWRIGHT_CORE || "playwright-core");

const [url, saida, escala = "2"] = process.argv.slice(2);
const FOLGA = 12;

if (!url || !saida) {
  console.error("uso: node capturar-cd.cjs <url do run> <saida.png> [escala]");
  process.exit(2);
}

(async () => {
  const navegador = await chromium.launch({ channel: "chrome", headless: true });
  const contexto = await navegador.newContext({
    viewport: { width: 1400, height: 900 },
    deviceScaleFactor: Number(escala),
    locale: "en-US",
    timezoneId: "UTC",
    colorScheme: "light",
  });
  const pagina = await contexto.newPage();
  await pagina.goto(url, { waitUntil: "domcontentloaded", timeout: 90000 });
  await pagina.waitForSelector(".WorkflowGraph .visual-graph .WorkflowCard", { timeout: 60000 });
  await pagina.waitForTimeout(3000);
  const grafo = await pagina.evaluate(() => {
    const caixas = [
      ...document.querySelectorAll(".WorkflowGraph .WorkflowCard, .WorkflowGraph .WorkflowConnector"),
    ].map((elemento) => elemento.getBoundingClientRect());
    return {
      jobs: [...document.querySelectorAll(".WorkflowGraph .WorkflowJob-title")].map((job) =>
        job.innerText.replace(/\s+/g, " ").trim(),
      ),
      x0: Math.min(...caixas.map((c) => c.left)),
      y0: Math.min(...caixas.map((c) => c.top + scrollY)),
      x1: Math.max(...caixas.map((c) => c.right)),
      y1: Math.max(...caixas.map((c) => c.bottom + scrollY)),
    };
  });
  const clip = {
    x: Math.floor(grafo.x0 - FOLGA),
    y: Math.floor(grafo.y0 - FOLGA),
    width: Math.ceil(grafo.x1 - grafo.x0 + 2 * FOLGA),
    height: Math.ceil(grafo.y1 - grafo.y0 + 2 * FOLGA),
  };
  await pagina.screenshot({ path: saida, fullPage: true, clip });
  // Os jobs lidos do grafo são o que se confere contra a API do run.
  console.log(JSON.stringify({ url, clip, escala: Number(escala), jobs: grafo.jobs }, null, 2));
  await navegador.close();
})().catch((erro) => {
  console.error(erro);
  process.exit(1);
});
