# Catastro Minero Argentina

Inventario normalizado y mapa de los derechos mineros de Argentina, armado desde
los catastros provinciales.

**Argentina no tiene catastro minero nacional.** Bajo el Código de Minería las
provincias son dueñas del recurso, así que cada una publica —o no— su propio
registro, con mecanismo de acceso y esquema distintos. Esto es la unión de las que
publican algo legible por máquina. No existe hoy otra vista pública unificada.

Al 2026-07-28: **19.671 derechos · 24,0 millones de hectáreas · 6 provincias ·
2.418 titulares**.

## Cobertura

| Provincia | Derechos | Superficie | % provincia | % con titular | Acceso |
|---|---:|---:|---:|---:|---|
| San Juan | 4.193 | 6,9 M ha | 76,7% | 44% | WFS `catastrominero.sanjuan.gob.ar` |
| Salta | 3.975 | 5,4 M ha | 34,8% | 90% | WFS GeoNode `geoportal.salta.gob.ar` |
| Catamarca | 2.385 | 5,7 M ha | 55,5% | 100% | WFS `nodoide.catamarca.gob.ar` |
| Neuquén | 6.629 | 2,1 M ha | 22,5% | 33% | KMZ `hidrocarburos.energianeuquen.gob.ar` |
| Córdoba | 705 | 176.362 ha | 1,1% | 0% | WFS IDECOR |
| Jujuy | 1.784 | 3,7 M ha | 70,4% | 99% | SHP `mineriajujuy.gob.ar` |

Sin datos abiertos: **Santa Cruz** (sólo un PDF de agosto 2023, y es de las más
importantes por producción), Chubut, Río Negro, Mendoza, La Rioja, San Luis. El
mapa las dibuja como ausencia explícita, nunca como territorio libre.

## Cómo funciona

```
scripts/fuentes.py     EL REGISTRO — una Fuente por capa. Dato, no código.
scripts/adapters/      wfs.py cubre 4 de 6 provincias; kml.py Neuquén; shp.py Jujuy
scripts/build.py       fuentes -> public/data/tenencias/<prov>.geojson
scripts/validate.py    gate de calidad: sale != 0 y bloquea el deploy
scripts/aggregate.py   índice nacional de titulares + rollups provinciales
scripts/health_check.py  ~15 probes diarios, detecta deriva sin descargar nada
src/                   Vite + React + Leaflet (canvas)
```

Agregar una provincia es agregar filas en `fuentes.py`, no escribir un módulo.

### Correr el pipeline

```bash
mamba env create -f environment.yml     # o usar el env `insar` existente
cd scripts
python test_normalize.py                # 65 casos, todos de datos reales
python build.py                         # usa el cache de raw/
python build.py --no-cache              # refetch completo
python validate.py                      # gate
python aggregate.py
python health_check.py                  # 0 sin cambios, 2 hay deriva
```

### Correr el sitio

```bash
npm install
npm run dev
npm run build && npm run preview
```

## Decisiones que vale la pena conocer

**Sin vector tiles.** Se midió: los derechos mineros son rectángulos mensurados,
**9,6 vértices por feature**. Simplificar no compra nada. El total nacional son
**2,0 MB gzip**, la provincia más grande 0,59 MB, cargada perezosamente. tippecanoe
+ PMTiles habría sido una dependencia nueva que además cuantiza coordenadas y
trunca atributos — justo lo que en un catastro *es* el producto. Revisar si algún
día se superan ~150k features.

**La geometría derivada no se commitea.** 21 MB refrescados semanalmente serían
~1 GB/año de objetos git. Se construye en CI y va al artifact de Pages; se
commitean sólo los agregados chicos, cuyo diff es la auditoría legible.

**Truncación silenciosa es el riesgo #1.** El adaptador WFS pagina y **asierta**
`recolectado == numberMatched`. Una provincia a medias publica un mapa equivocado
que nadie nota. San Juan además rechaza `startIndex` (son vistas sin PK), así que
el adaptador cae a una sola request y mantiene el assert.

**Procedencia por feature.** Cada derecho lleva URL exacta de la consulta, capa,
CRS de origen, fecha de descarga y licencia, visibles al hacer clic. Ningún visor
provincial oficial te dice de cuándo es el corte.

## Advertencias sobre los datos

- **Deriva semántica.** «Mina» en Salta no es «mina padrón» en San Juan; «vigente»
  no tiene definición legal compartida entre códigos provinciales. Se conserva
  siempre `tipo_origen` / `estado_origen` / `mineral_origen`.
- **Sesgo de incompletitud.** Las provincias con buenos datos *parecen* más
  concesionadas. El sesgo está documentado en la vista Cobertura.
- **El ranking de titulares es de lo publicado, no de la realidad.** 7.917 derechos
  no informan titular; los cateos de San Juan nunca lo traen.
- **Duplicación de origen.** La vista `vw_minas_padron` de San Juan hace fan-out:
  213 de 4.406 filas (4,8%) eran copias idénticas. Se colapsan y se cuentan en
  `cobertura.json`.
- **Mails de titulares.** El export de Jujuy incluye un campo `dom_corre` con
  direcciones de correo de los titulares. Se descarta en el adaptador y nunca se
  publica; `strip_pii` además borra mails y documentos de cualquier campo libre.
- **Personas físicas.** El titular es a menudo una persona. El registro es público,
  pero el ranking nacional lista empresas por nombre y agrega a las personas en un
  conteo; nunca se publica DNI/CUIT.

## Licencia

Código MIT. **Datos: derivados de fuentes provinciales, licencia por fuente.**
Ninguna provincia declara una licencia explícita hoy, así que todas figuran como
`no_especificada`. Lo que sí es sólido: el catastro minero es **registro público
por ley** (el Código de Minería exige publicidad de manifestaciones, mensuras y
padrón), y republicar un registro público con atribución es defendible. **Verificar
licencia provincia por provincia antes de cualquier uso comercial** — el precedente
CC-BY-4.0 de `datos.energia.gob.ar` es nacional y no se transfiere.

Correcciones y pedidos de baja: abrir un issue.
