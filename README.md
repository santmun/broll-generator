# B-roll Generator

Genera imagenes de B-roll con estilo hand-drawn para videos usando Kie AI (Nano Banana Pro). Incluye 3 estilos visuales y generacion en paralelo.

## Componentes

| Archivo | Descripcion |
|---------|-------------|
| `.claude/agents/broll-director.md` | Agent de Claude Code que analiza guiones y genera conceptos visuales |
| `scripts/generate-broll.py` | Script Python de generacion via Kie AI API (paralelo) |

## 3 Estilos Visuales

| Estilo | Descripcion | Uso |
|--------|-------------|-----|
| **A - Conceptual** | Acuarela + fondo beige + texto breve en espanol | Conceptos abstractos, comparaciones |
| **B - Iconos** | Lapices de colores + fondo blanco + sin texto | Herramientas, flujos tecnicos |
| **C - Sketchnote** | Journal/bullet journal + papel crema + titulo cursivo | Infografias, resumen visual |

## Formatos Soportados

- `16:9` - YouTube, presentaciones (default)
- `9:16` - TikTok, Reels, Stories
- `1:1` - Instagram Feed, LinkedIn
- Mixto: "50% 1:1 50% 9:16"

## Requisitos

- Python 3.8+
- `pip install requests python-dotenv`
- API key de Kie AI (`KIE_AI_API_KEY`)

## Uso

### Flujo con Claude Code
1. El agent `broll-director` lee los guiones del video
2. Genera conceptos visuales y prompts en `broll.md`
3. El script ejecuta la generacion con Kie AI

### Script standalone
```bash
export KIE_AI_API_KEY="tu-api-key"
python3 scripts/generate-broll.py "bundle_id"
python3 scripts/generate-broll.py "bundle_id" --concurrency 10
```

## Output

- Imagenes en `/outputs/bundles/[bundle_id]/broll/`
- Guia para editor (`guia-editor-broll.docx`) con mapeo imagen-guion
- Copia automatica a Google Drive

## Costo Estimado

~$0.10 por imagen | 10 imagenes = ~$1.00
