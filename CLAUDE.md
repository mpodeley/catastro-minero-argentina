# CLAUDE.md

## Qué es este repo

Inventario + mapa de derechos mineros de Argentina. Pipeline Python baja los
catastros provinciales, normaliza a un esquema común y escribe GeoJSON bajo
`public/data/`; el frontend (Vite + React + Leaflet) los lee en runtime. Sitio
estático a GitHub Pages, refrescado semanalmente por GitHub Actions.

UX en español; comentarios y nombres de variables en inglés.

## Comandos

```bash
# El env geoespacial es conda-first. `insar` ya alcanza.
PY="~/miniforge3/bin/mamba run -n insar python"

cd scripts
$PY test_normalize.py      # 76 casos, todos derivados de datos reales
$PY build.py               # fuentes -> public/data/tenencias/
$PY validate.py            # gate: sale != 0 y bloquea el deploy
$PY aggregate.py
$PY health_check.py        # 0 = sin cambios, 2 = deriva

npm run dev
npx tsc --noEmit
npm run build
```

## Arquitectura

**`scripts/fuentes.py` es el registro y la fuente de verdad.** Una `Fuente` por
capa provincial. Agregar una provincia = agregar filas, no escribir un módulo.
5 de 7 provincias son el mismo `WfsAdapter` parametrizado; Neuquén usa `kml.py`
y Jujuy `shp.py`.

Al sumar una provincia hay que tocar **`AREA_PROV_KM2` en `validate.py`**: sin la
superficie, el gate que detecta errores de CRS (>100% de la provincia titulada)
se saltea en silencio, y `aggregate.py` —que importa esa misma tabla— deja
`pct_provincia` en `None`, con lo que el coropleto pinta la provincia fuera de
la rampa.

Flujo: `fetch` (cache por sha256 en `raw/`) → `parse` → `normalize` → `dedupe` →
`with_area` → GeoJSON por provincia + por tipo de geometría.

## Invariantes que no hay que romper

- **El assert de paginación del WFS.** `recolectado == numberMatched`, siempre.
  GeoServer trunca en silencio en muchas instalaciones y una provincia a medias
  publica un mapa equivocado que nadie nota. Es el riesgo de corrección #1.
- **San Juan rechaza `startIndex`** (son vistas sin primary key): el adaptador
  cae a una request única y mantiene el assert. No "arreglar" reintroduciendo
  paginación incondicional.
- **Neuquén: el tipo sale de la CARPETA del KML**, no de los atributos. La fila
  «Nombre» es la denominación y sólo existe en 2.167 de 6.629 registros. Leerla
  como tipo mislabelea ~83% de la provincia y el resultado *parece* correcto.
- **Fail-soft por provincia.** Una fuente caída no puede voltear el build. Sólo
  un fallo global o un FAIL de `validate.py` aborta.
- **`public/data/tenencias/` está gitignoreado** a propósito. 21 MB semanales
  serían ~1 GB/año de objetos git. Se construye en CI.
- **`health_check.py` compara cantidades comparables**: `features_fuente` (antes
  de dedupe) contra el conteo del servidor, y `bytes_descarga` (tamaño
  transferido) contra el Content-Length. Mezclarlas produce falsos positivos
  de -7000%.

## Gotchas de datos

- `parse_ha("774,7280 ha")` → coma decimal. Si hay coma Y punto, el punto es
  separador de miles.
- Salta sirve fechas como `'2013-07-29Z'`: fecha con Z colgada, `fromisoformat`
  la rechaza.
- `map_estado`/`map_tipo` sólo hacen substring match con fragmentos de ≥4 chars.
  El `"si"` de Neuquén (columna Vigencia booleana) matchearía dentro de
  "sin publicar" y "desistido".
- Los períodos se colapsan ANTES que el resto de la puntuación en `_tokens()`,
  si no "S.A." se parte en "S"+"A" y Glencore queda clasificada como persona
  física, fuera del ranking de empresas.
- EPSG **22173 es POSGAR 98**, no Campo Inchauspe (ése es 22193). 2217x/2218x/
  2219x son tres datums distintos con códigos adyacentes: resolver siempre por
  `pyproj.CRS.from_epsg()` y loguear el datum.
- **Jujuy: el DBF es latin-1**, no UTF-8 — pyshp muere en el primer símbolo de
  grado. Y el campo `dom_corre` trae MAILS de titulares: se descarta en el
  adaptador, nunca se parsea al esquema.
- Jujuy trae la capa combinada `CATASTRO_MINERO` en la raíz del zip y además las
  9 carpetas por tipo con los mismos 1.784 registros. Leer las dos duplicaría.
- El PHP de descarga de Jujuy responde HEAD con 20 bytes: un tamaño implausible
  se reporta como desconocido, si no la deriva salta al -100% para siempre.
- Salta publica `coordenadas` (WKT Gauss-Krüger) además de la geometría 4326:
  es una doble representación regalada, la usa el round-trip de CRS. Nunca se
  manda al browser (es ~40% del payload).

## Verificaciones de referencia

Contrastar contra estos números; un desvío el día 1 significa que algo se rompió.

- San Juan `vw_minas_padron` 1.378 crudos → 1.166 tras dedupe · Salta 3.964 ·
  Catamarca `idecat:MINAS_19022026` 2.385 · Neuquén 6.629 placemarks ·
  Jujuy `CATASTRO_MINERO` 1.784 · Mendoza 356 minas + 390 canteras + 514 cateos
  + 456 manifestaciones + 3 plantas + 1 servidumbre = 1.715 tras descartes
- Total nacional: 21.386 derechos, 25,8 M ha, 7 provincias, 2.991 titulares
- Golden record: San Juan `VEGA AZUL`, Calingasta, `GLENCORE PACHON S.A`,
  64,3859 ha declaradas vs 64,5348 calculadas (0,23%)
- Round-trip de CRS contra el WKT de Salta: desviación máxima 0,60 m (gate < 5 m)
- Mediana de error de superficie: San Juan 0,18% · Salta 0,03% · Jujuy 0,06%
  (gate < 2%) — Jujuy valida la reproyección POSGAR 94 faja 3
