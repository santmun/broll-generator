#!/usr/bin/env python3
"""
generate-broll.py - Genera imágenes de B-roll usando Kie AI (Nano Banana Pro)

Uso: python3 scripts/generate-broll.py <bundle_id> [--concurrency N]
Ejemplo: python3 scripts/generate-broll.py 2026-01-20-tutorial-n8n
         python3 scripts/generate-broll.py 2026-01-20-tutorial-n8n --concurrency 10

Requiere:
- KIE_AI_API_KEY en variables de entorno o hardcodeada
- broll.md generado por el agente broll-director

Soporta generación en PARALELO: todas las imágenes se envían a la API
simultáneamente y se descargan conforme terminan. --concurrency controla
cuántas tareas se procesan al mismo tiempo (default: 5).
"""

import os
import sys
import json
import re
import time
import shutil
import subprocess
import requests
import threading
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configuración
PROJECT_ROOT = Path("/Users/santiagomunoz/Documents/Copia de agentesanmunoz")
BUNDLES_PATH = PROJECT_ROOT / "outputs" / "bundles"
GOOGLE_DRIVE_BROLL = Path("/Users/santiagomunoz/Library/CloudStorage/GoogleDrive-contacto@innovandohorizontes.com/Mi unidad/BROLL")

# Kie AI Configuration - API correcta
KIE_AI_API_KEY = "5e1db509c0a31d2aff22516899d22510"
KIE_AI_BASE_URL = "https://api.kie.ai/api/v1/jobs"
KIE_AI_MODEL = "nano-banana-pro"

# Polling configuration
MAX_POLL_ATTEMPTS = 60  # Máximo 60 intentos
POLL_INTERVAL = 3  # Segundos entre cada intento

# Parallel generation config
DEFAULT_CONCURRENCY = 5  # Tareas simultáneas por defecto
MAX_CONCURRENCY = 15  # Máximo de tareas simultáneas

# Thread-safe print lock
_print_lock = threading.Lock()

# Colores para output
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    CYAN = '\033[0;36m'
    NC = '\033[0m'  # No Color


def print_header(bundle_id: str):
    """Imprime header del script"""
    print()
    print(f"{Colors.CYAN}╔════════════════════════════════════════════════════════╗{Colors.NC}")
    print(f"{Colors.CYAN}║  GENERATE B-ROLL IMAGES (Kie AI / Nano Banana Pro)     ║{Colors.NC}")
    print(f"{Colors.CYAN}╠════════════════════════════════════════════════════════╣{Colors.NC}")
    print(f"{Colors.CYAN}║{Colors.NC}  Bundle: {bundle_id}")
    print(f"{Colors.CYAN}╚════════════════════════════════════════════════════════╝{Colors.NC}")
    print()


def load_broll_config(bundle_path: Path) -> dict:
    """Carga la configuración de B-roll desde broll.md"""
    broll_file = bundle_path / "broll.md"

    if not broll_file.exists():
        print(f"{Colors.RED}Error: No existe broll.md en {bundle_path}{Colors.NC}")
        print(f"{Colors.YELLOW}Ejecuta primero el agente broll-director para generar los conceptos.{Colors.NC}")
        sys.exit(1)

    content = broll_file.read_text(encoding='utf-8')

    # Buscar el bloque JSON en el archivo
    json_match = re.search(r'```json\s*(\{[\s\S]*?"broll_images"[\s\S]*?\})\s*```', content)

    if not json_match:
        print(f"{Colors.RED}Error: No se encontró el bloque JSON en broll.md{Colors.NC}")
        print(f"{Colors.YELLOW}Asegúrate de que broll.md contenga un bloque ```json con 'broll_images'{Colors.NC}")
        sys.exit(1)

    try:
        config = json.loads(json_match.group(1))
        return config
    except json.JSONDecodeError as e:
        print(f"{Colors.RED}Error: JSON inválido en broll.md: {e}{Colors.NC}")
        sys.exit(1)


def create_image_task(prompt: str, aspect_ratio: str, api_key: str) -> str:
    """Crea una tarea de generación de imagen y retorna el taskId"""

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": KIE_AI_MODEL,
        "input": {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "resolution": "2K",
            "output_format": "png"
        }
    }

    response = requests.post(
        f"{KIE_AI_BASE_URL}/createTask",
        headers=headers,
        json=payload,
        timeout=30
    )

    if response.status_code != 200:
        raise Exception(f"Error creando tarea: {response.status_code} - {response.text}")

    result = response.json()

    if result.get("code") != 200:
        raise Exception(f"API error: {result.get('msg', 'Unknown error')}")

    task_id = result.get("data", {}).get("taskId")
    if not task_id:
        raise Exception(f"No se recibió taskId: {result}")

    return task_id


def poll_task_result(task_id: str, api_key: str) -> str:
    """Espera a que la tarea termine y retorna la URL de la imagen"""

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    for attempt in range(MAX_POLL_ATTEMPTS):
        response = requests.get(
            f"{KIE_AI_BASE_URL}/recordInfo?taskId={task_id}",
            headers=headers,
            timeout=30
        )

        if response.status_code != 200:
            raise Exception(f"Error consultando tarea: {response.status_code}")

        result = response.json()

        if result.get("code") != 200:
            raise Exception(f"API error: {result.get('msg', 'Unknown error')}")

        data = result.get("data", {})
        state = data.get("state")  # Kie AI usa "state" no "status"

        if state == "success":
            # Buscar URL de imagen en resultJson
            result_json_str = data.get("resultJson", "{}")
            try:
                result_json = json.loads(result_json_str) if isinstance(result_json_str, str) else result_json_str
            except json.JSONDecodeError:
                result_json = {}

            # Buscar en resultUrls (estructura de Kie AI)
            result_urls = result_json.get("resultUrls", [])
            if result_urls:
                return result_urls[0]

            # Fallback: buscar en otras estructuras posibles
            image_url = result_json.get("image_url") or result_json.get("url")
            if image_url:
                return image_url

            # Intentar en data directamente
            if "resultUrls" in data:
                return data["resultUrls"][0]

            raise Exception(f"Tarea completada pero sin URL de imagen: {result}")

        elif state == "fail":
            fail_msg = data.get("failMsg", data.get("failCode", "Unknown error"))
            raise Exception(f"Tarea fallida: {fail_msg}")

        elif state in ["pending", "processing", "running", None]:
            # Aún procesando, esperar
            time.sleep(POLL_INTERVAL)

        else:
            # Estado desconocido, seguir esperando
            time.sleep(POLL_INTERVAL)

    raise Exception(f"Timeout esperando resultado después de {MAX_POLL_ATTEMPTS * POLL_INTERVAL} segundos")


def download_image(image_url: str) -> bytes:
    """Descarga la imagen desde la URL"""
    response = requests.get(image_url, timeout=60)
    if response.status_code != 200:
        raise Exception(f"Error descargando imagen: {response.status_code}")
    return response.content


def generate_image(prompt: str, aspect_ratio: str, api_key: str) -> bytes:
    """Genera una imagen usando Kie AI (proceso completo)"""

    # 1. Crear tarea
    task_id = create_image_task(prompt, aspect_ratio, api_key)

    # 2. Esperar resultado
    image_url = poll_task_result(task_id, api_key)

    # 3. Descargar imagen
    image_data = download_image(image_url)

    return image_data


def save_image(image_data: bytes, output_path: Path):
    """Guarda la imagen en disco"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(image_data)


def copy_to_google_drive(bundle_id: str, local_broll_path: Path):
    """Copia las imágenes generadas a Google Drive"""
    drive_folder = GOOGLE_DRIVE_BROLL / bundle_id

    if not GOOGLE_DRIVE_BROLL.exists():
        print(f"{Colors.YELLOW}⚠️  Carpeta de Google Drive no encontrada: {GOOGLE_DRIVE_BROLL}{Colors.NC}")
        print(f"{Colors.YELLOW}   Las imágenes solo se guardaron localmente.{Colors.NC}")
        return False

    try:
        # Crear carpeta del bundle en Google Drive
        drive_folder.mkdir(parents=True, exist_ok=True)

        # Copiar todos los archivos PNG
        copied = 0
        for img_file in local_broll_path.glob("*.png"):
            dest = drive_folder / img_file.name
            shutil.copy2(img_file, dest)
            copied += 1

        # Copiar el manifest si existe
        manifest = local_broll_path / "manifest.json"
        if manifest.exists():
            shutil.copy2(manifest, drive_folder / "manifest.json")

        print(f"{Colors.GREEN}✅ {copied} imágenes copiadas a Google Drive{Colors.NC}")
        print(f"   📁 {drive_folder}")
        return True

    except Exception as e:
        print(f"{Colors.RED}Error copiando a Google Drive: {e}{Colors.NC}")
        return False


def generate_editor_guide(bundle_id: str, bundle_path: Path, broll_images: list):
    """Genera la guía del editor en formato Word"""

    print(f"{Colors.YELLOW}Generando guía para editor...{Colors.NC}")

    # Leer broll.md para extraer los fragmentos del guion
    broll_file = bundle_path / "broll.md"
    broll_content = broll_file.read_text(encoding='utf-8') if broll_file.exists() else ""

    # Crear contenido markdown para la guía
    guide_content = f"""# Guía de B-roll para Editor

## Video: {bundle_id}

Este documento indica en qué momento del guion debe aparecer cada imagen de B-roll.

---

"""

    for img in broll_images:
        img_id = img.get("id", 0)
        scene = img.get("scene", "Sin nombre")
        formats = img.get("formats", ["16:9"])
        text_in_image = img.get("text_in_image", "N/A")
        prompt = img.get("prompt", "")

        # Determinar el formato del archivo
        ratio_slug = formats[0].replace(":", "x") if formats else "16x9"
        if isinstance(img_id, int):
            filename = f"broll-{img_id:02d}-{ratio_slug}.png"
        else:
            filename = f"broll-{str(img_id).lower()}-{ratio_slug}.png"

        # Buscar el fragmento del guion en broll.md
        # Buscar patrón "Momento en guion": "..."
        pattern = rf'### Escena {img_id}:.*?Momento en guion["\s:]*[">]([^"<\n]+)'
        match = re.search(pattern, broll_content, re.IGNORECASE | re.DOTALL)

        if match:
            guion_fragment = match.group(1).strip().strip('"').strip("*").strip()
        else:
            # Fallback: usar el nombre de la escena
            guion_fragment = f"[Escena: {scene}]"

        # Extraer descripción corta del prompt (primeras 2 oraciones)
        prompt_sentences = prompt.split(".")
        short_desc = ". ".join(prompt_sentences[:2]).strip()
        if short_desc and not short_desc.endswith("."):
            short_desc += "."

        # Agregar texto en imagen si existe
        text_info = f' Texto: "{text_in_image}"' if text_in_image and text_in_image != "N/A" else " Sin texto."

        guide_content += f"""## Imagen {img_id}: {filename}

**Fragmento del guion:**
> "{guion_fragment}"

**Descripción de la imagen:** {short_desc}{text_info}

---

"""

    # Agregar resumen de formatos
    format_1x1 = [img for img in broll_images if "1:1" in img.get("formats", [])]
    format_9x16 = [img for img in broll_images if "9:16" in img.get("formats", [])]
    format_16x9 = [img for img in broll_images if "16:9" in img.get("formats", [])]

    guide_content += """## Resumen de Formatos

| Formato | Cantidad | Uso recomendado |
|---------|----------|-----------------|
"""
    if format_1x1:
        ids_1x1 = ", ".join([str(img.get("id")) for img in format_1x1])
        guide_content += f"| 1:1 (cuadrado) | {len(format_1x1)} | Feed, overlay (imágenes {ids_1x1}) |\n"
    if format_9x16:
        ids_9x16 = ", ".join([str(img.get("id")) for img in format_9x16])
        guide_content += f"| 9:16 (vertical) | {len(format_9x16)} | Stories, Reels (imágenes {ids_9x16}) |\n"
    if format_16x9:
        ids_16x9 = ", ".join([str(img.get("id")) for img in format_16x9])
        guide_content += f"| 16:9 (horizontal) | {len(format_16x9)} | YouTube (imágenes {ids_16x9}) |\n"

    # Guardar markdown
    guide_md_path = bundle_path / "guia-editor-broll.md"
    guide_md_path.write_text(guide_content, encoding='utf-8')

    # Generar Word usando el skill word-doc
    try:
        word_script = PROJECT_ROOT / ".claude" / "skills" / "word-doc" / "scripts" / "create-word.py"
        guide_docx_path = bundle_path / "guia-editor-broll.docx"

        if word_script.exists():
            result = subprocess.run(
                [
                    "python3",
                    str(word_script),
                    "Guía de B-roll para Editor",
                    str(guide_md_path),
                    str(guide_docx_path)
                ],
                capture_output=True,
                text=True,
                cwd=str(PROJECT_ROOT)
            )

            if result.returncode == 0:
                print(f"{Colors.GREEN}✅ Guía del editor generada: guia-editor-broll.docx{Colors.NC}")
                return True
            else:
                print(f"{Colors.YELLOW}⚠️  Error generando Word: {result.stderr}{Colors.NC}")
                print(f"{Colors.YELLOW}   Guía disponible en formato .md{Colors.NC}")
                return False
        else:
            print(f"{Colors.YELLOW}⚠️  Script word-doc no encontrado{Colors.NC}")
            print(f"{Colors.YELLOW}   Guía disponible en: guia-editor-broll.md{Colors.NC}")
            return False

    except Exception as e:
        print(f"{Colors.YELLOW}⚠️  Error generando Word: {e}{Colors.NC}")
        print(f"{Colors.YELLOW}   Guía disponible en: guia-editor-broll.md{Colors.NC}")
        return False


def _safe_print(*args, **kwargs):
    """Thread-safe print"""
    with _print_lock:
        print(*args, **kwargs)


def _generate_single_image(task: dict, output_path: Path, api_key: str, total: int, skip_existing: bool = False) -> dict:
    """Genera una sola imagen (para ejecución paralela). Retorna resultado."""
    img_id = task["id"]
    scene = task["scene"]
    prompt = task["prompt"]
    aspect_ratio = task["aspect_ratio"]
    index = task["index"]
    ratio_slug = aspect_ratio.replace(":", "x")

    if isinstance(img_id, int):
        filename = f"broll-{img_id:02d}-{ratio_slug}.png"
    else:
        filename = f"broll-{str(img_id).lower()}-{ratio_slug}.png"

    output_file = output_path / filename

    # Skip si ya existe y tiene contenido
    if skip_existing and output_file.exists() and output_file.stat().st_size > 1000:
        _safe_print(f"  ⏭️  [{index}/{total}] Escena {img_id} ({aspect_ratio}) — ya existe, saltando", flush=True)
        return {
            "success": True,
            "skipped": True,
            "id": img_id,
            "scene": scene,
            "format": aspect_ratio,
            "filename": filename,
            "path": str(output_file)
        }

    _safe_print(f"  🚀 [{index}/{total}] Escena {img_id} ({aspect_ratio}) — enviando...", flush=True)

    try:
        # 1. Crear tarea en la API
        task_id = create_image_task(prompt, aspect_ratio, api_key)
        _safe_print(f"  ⏳ [{index}/{total}] Escena {img_id} ({aspect_ratio}) — procesando (task: {task_id[:12]}...)", flush=True)

        # 2. Esperar resultado
        image_url = poll_task_result(task_id, api_key)

        # 3. Descargar imagen
        image_data = download_image(image_url)
        save_image(image_data, output_file)

        _safe_print(f"  {Colors.GREEN}✅ [{index}/{total}] Escena {img_id}: {scene} ({aspect_ratio}) — listo{Colors.NC}", flush=True)

        return {
            "success": True,
            "id": img_id,
            "scene": scene,
            "format": aspect_ratio,
            "filename": filename,
            "path": str(output_file)
        }

    except Exception as e:
        _safe_print(f"  {Colors.RED}❌ [{index}/{total}] Escena {img_id}: {scene} ({aspect_ratio}) — Error: {e}{Colors.NC}", flush=True)
        return {
            "success": False,
            "id": img_id,
            "scene": scene,
            "format": aspect_ratio,
            "error": str(e)
        }


def generate_broll_images(bundle_id: str, concurrency: int = DEFAULT_CONCURRENCY, skip_existing: bool = False):
    """Genera todas las imágenes de B-roll para un bundle (en PARALELO)"""

    # Usar API key configurada o variable de entorno
    api_key = os.environ.get("KIE_AI_API_KEY") or KIE_AI_API_KEY
    if not api_key:
        print(f"{Colors.RED}Error: KIE_AI_API_KEY no configurada{Colors.NC}")
        sys.exit(1)

    # Verificar bundle
    bundle_path = BUNDLES_PATH / bundle_id
    if not bundle_path.exists():
        print(f"{Colors.RED}Error: No existe el bundle {bundle_id}{Colors.NC}")
        print(f"\nBundles disponibles:")
        for b in sorted(BUNDLES_PATH.iterdir()):
            if b.is_dir():
                print(f"  - {b.name}")
        sys.exit(1)

    print_header(bundle_id)

    # Cargar configuración
    print(f"{Colors.YELLOW}Cargando configuración de broll.md...{Colors.NC}")
    config = load_broll_config(bundle_path)

    broll_images = config.get("broll_images", [])
    if not broll_images:
        print(f"{Colors.RED}Error: No se encontraron imágenes en la configuración{Colors.NC}")
        sys.exit(1)

    # Construir lista plana de tareas (una por imagen/formato)
    tasks = []
    index = 0
    for img_config in broll_images:
        img_id = img_config.get("id", "unknown")
        scene = img_config.get("scene", "untitled")
        prompt = img_config.get("prompt", "")
        formats = img_config.get("formats", ["16:9"])

        if not prompt:
            print(f"{Colors.YELLOW}⚠️  Escena {img_id} sin prompt, saltando...{Colors.NC}")
            continue

        for aspect_ratio in formats:
            index += 1
            tasks.append({
                "id": img_id,
                "scene": scene,
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "index": index
            })

    total_images = len(tasks)
    concurrency = min(concurrency, MAX_CONCURRENCY, total_images)

    print(f"{Colors.BLUE}Imágenes a generar: {total_images} ({len(broll_images)} escenas){Colors.NC}")
    print(f"{Colors.BLUE}Modelo: {KIE_AI_MODEL}{Colors.NC}")
    print(f"{Colors.BLUE}Concurrencia: {concurrency} tareas simultáneas{Colors.NC}")
    if skip_existing:
        print(f"{Colors.BLUE}Skip existing: activado (no regenera imágenes existentes){Colors.NC}")
    print()

    # Crear carpeta de output
    output_path = bundle_path / "broll"
    output_path.mkdir(parents=True, exist_ok=True)

    # Generar imágenes EN PARALELO
    generated = []
    skipped = []
    errors = []
    start_time = time.time()

    print(f"{Colors.CYAN}━━━ Lanzando {total_images} generaciones en paralelo ━━━{Colors.NC}")
    print()

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(_generate_single_image, task, output_path, api_key, total_images, skip_existing): task
            for task in tasks
        }

        for future in as_completed(futures):
            result = future.result()
            if result["success"]:
                entry = {
                    "id": result["id"],
                    "scene": result["scene"],
                    "format": result["format"],
                    "filename": result["filename"],
                    "path": result["path"]
                }
                if result.get("skipped"):
                    skipped.append(entry)
                else:
                    generated.append(entry)
            else:
                errors.append({
                    "id": result["id"],
                    "scene": result["scene"],
                    "format": result["format"],
                    "error": result["error"]
                })

    elapsed = time.time() - start_time
    elapsed_min = elapsed / 60

    # Ordenar por ID para manifest consistente
    all_successful = generated + skipped
    all_successful.sort(key=lambda x: (x["id"] if isinstance(x["id"], int) else 0, x["format"]))

    # Guardar manifest
    manifest = {
        "bundle_id": bundle_id,
        "generated_at": datetime.now().isoformat(),
        "model": KIE_AI_MODEL,
        "mode": "parallel",
        "concurrency": concurrency,
        "elapsed_seconds": round(elapsed, 1),
        "total_scenes": len(broll_images),
        "total_images": len(all_successful),
        "newly_generated": len(generated),
        "skipped_existing": len(skipped),
        "errors": len(errors),
        "images": all_successful,
        "failed": errors
    }

    manifest_path = output_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')

    # Copiar a Google Drive
    print()
    print(f"{Colors.YELLOW}Copiando a Google Drive...{Colors.NC}")
    copy_to_google_drive(bundle_id, output_path)

    # Generar guía para editor
    generate_editor_guide(bundle_id, bundle_path, broll_images)

    # Resumen final
    print()
    print(f"{Colors.BLUE}╔════════════════════════════════════════════════════════╗{Colors.NC}")
    print(f"{Colors.BLUE}║  RESUMEN                                               ║{Colors.NC}")
    print(f"{Colors.BLUE}╠════════════════════════════════════════════════════════╣{Colors.NC}")
    print(f"{Colors.BLUE}║{Colors.NC}  Escenas procesadas: {len(broll_images)}")
    print(f"{Colors.BLUE}║{Colors.NC}  {Colors.GREEN}Imágenes generadas: {len(generated)}{Colors.NC}")
    if skipped:
        print(f"{Colors.BLUE}║{Colors.NC}  ⏭️  Ya existían (skip): {len(skipped)}")

    if errors:
        print(f"{Colors.BLUE}║{Colors.NC}  {Colors.RED}Errores: {len(errors)}{Colors.NC}")

    print(f"{Colors.BLUE}║{Colors.NC}  ⏱️  Tiempo total: {elapsed_min:.1f} min ({elapsed:.0f}s)")
    print(f"{Colors.BLUE}║{Colors.NC}  ⚡ Concurrencia: {concurrency} tareas simultáneas")
    print(f"{Colors.BLUE}║{Colors.NC}  📁 Local: {output_path}")
    print(f"{Colors.BLUE}╚════════════════════════════════════════════════════════╝{Colors.NC}")
    print()

    if errors:
        print(f"{Colors.YELLOW}⚠️  Algunas imágenes fallaron. Revisa los errores arriba.{Colors.NC}")
        return 1
    else:
        print(f"{Colors.GREEN}✅ B-roll generado exitosamente{Colors.NC}")
        return 0


def main():
    if len(sys.argv) < 2:
        print(f"{Colors.RED}Error: Falta el bundle_id{Colors.NC}")
        print(f"Uso: python3 {sys.argv[0]} <bundle_id> [--concurrency N]")
        print(f"Ejemplo: python3 {sys.argv[0]} 2026-01-20-tutorial-n8n")
        print(f"         python3 {sys.argv[0]} 2026-01-20-tutorial-n8n --concurrency 10")
        print()
        print("Bundles disponibles:")
        for b in sorted(BUNDLES_PATH.iterdir()):
            if b.is_dir() and (b / "broll.md").exists():
                print(f"  - {b.name} (tiene broll.md)")
            elif b.is_dir():
                print(f"  - {b.name}")
        sys.exit(1)

    bundle_id = sys.argv[1]

    # Parse --concurrency flag
    concurrency = DEFAULT_CONCURRENCY
    if "--concurrency" in sys.argv:
        try:
            idx = sys.argv.index("--concurrency")
            concurrency = int(sys.argv[idx + 1])
            concurrency = max(1, min(concurrency, MAX_CONCURRENCY))
        except (IndexError, ValueError):
            print(f"{Colors.YELLOW}⚠️  --concurrency inválido, usando default ({DEFAULT_CONCURRENCY}){Colors.NC}")

    # Parse --skip-existing flag
    skip_existing = "--skip-existing" in sys.argv

    sys.exit(generate_broll_images(bundle_id, concurrency=concurrency, skip_existing=skip_existing))


if __name__ == "__main__":
    main()
