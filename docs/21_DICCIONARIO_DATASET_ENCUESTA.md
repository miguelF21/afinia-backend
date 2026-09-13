# DICCIONARIO DEL DATASET DE LA ENCUESTA (Afinia)

Este documento define la estructura analítica de las respuestas obtenidas a través de la encuesta de Google Forms, la cual sirve como baseline de datos para Afinia.

## SECCIÓN 1. Información General (Demografía)

### 1. Edad
- **Pregunta Original:** (Asumida implícita antes de la 3, ej: ¿Cuál es tu edad?)
- **Nombre Técnico:** `edad`
- **Descripción:** Edad cronológica del encuestado.
- **Tipo Estadístico:** Numérica (Continua/Discreta).
- **Valores Posibles:** Rango numérico (ej: 18 a 50).
- **Transformación:** Ninguna, limpieza de ruido (si escribieron "18 años" -> `18`).
- **Utilización Analítica:** Variable demográfica para agrupar y analizar diferencias en preferencias según edad.

### 2. Género
- **Pregunta Original:** (Asumida implícita, ej: Género)
- **Nombre Técnico:** `genero`
- **Tipo Estadístico:** Nominal.
- **Transformación:** Normalización a minúsculas (`masculino`, `femenino`, `otro`).
- **Utilización:** Variable de agrupación clave para diagnosticar diferencias en preferencias por género.

### 3. Semestre
- **Pregunta Original:** 3. ¿En qué rango de semestre te encuentras?
- **Nombre Técnico:** `rango_semestre`
- **Tipo Estadístico:** Ordinal.
- **Valores Posibles:** "1.º-2.º", "3.º-4.º", "5.º-6.º", "7.º-8.º", "9.º-10.º", "Otro".
- **Transformación:** Mapeo numérico ordinal: 1 a 6.

## SECCIÓN 2. Experiencia y Situación Sentimental

### 4. Situación Sentimental
- **Pregunta Original:** 4. ¿Cuál es tu situación sentimental actual?
- **Nombre Técnico:** `situacion_sentimental`
- **Tipo Estadístico:** Nominal.
- **Valores Posibles:** Soltero/a, En una relación, Saliendo, Prefiero no responder.
- **Transformación:** One-Hot Encoding si se usa predictivamente, sino descriptiva.

### 5. Intención de Relación (Target Inicial Propuesto)
- **Pregunta Original:** 7. Cuando conoces a alguien... ¿qué tipo de relación buscas principalmente?
- **Nombre Técnico:** `tipo_relacion_buscada` (Variable Objetivo)
- **Tipo Estadístico:** Nominal (Multirespuesta original, se modelará Binaria).
- **Valores Posibles Originales:** Relación seria, Conocer a la persona, Algo casual, No busco, Depende, Prefiero no responder.
- **Transformación:** Binaria -> `RELACION_SERIA` (Si contiene "Una relación seria y estable") vs `OTRA_ORIENTACION` (Cualquier otra respuesta válida).

## SECCIÓN 3. Características Valoradas

### 8. Cuadrícula Likert de Importancia (18 variables)
- **Pregunta Original:** 8. Al elegir una posible pareja, ¿qué tan importante es para ti cada una...?
- **Nombre Técnico (Ejemplos):** 
  - `imp_atractivo_fisico`
  - `imp_personalidad`
  - `imp_humor`
  - `imp_inteligencia`
  - `imp_comunicacion`
  - `imp_valores`
  - `imp_intereses`
  - `imp_estabilidad_emocional`
- **Tipo Estadístico:** Ordinal.
- **Valores Posibles:** 1 (Nada) a 5 (Muy importante).
- **Transformación:** Conservar el entero (1-5).
- **Utilización Analítica:** Features (X) principales del modelo predictivo para inferir el tipo de relación buscada. 

### 9. Top 3 Características
- **Pregunta Original:** 9. Si tuvieras que escoger solamente TRES características...
- **Nombre Técnico:** `top3_caracteristicas`
- **Tipo Estadístico:** Nominal Multirespuesta.
- **Transformación:** Multi-hot encoding. Se crearán N columnas binarias (`top3_atractivo`, `top3_personalidad`, etc.) donde 1 indica selección.

## SECCIÓN 4. Similitud y Compatibilidad

### 11-14. Escalas de Similitud
- **Nombres Técnicos:** `pref_similitud_gustos`, `pref_similitud_valores`, `pref_similitud_metas`
- **Tipo Estadístico:** Ordinal (1 a 5).
- **Transformación:** Conversión a variable numérica de intervalo (1, 2, 3, 4, 5).

## SECCIÓN 5. Influencia de Experiencias Anteriores

### 20. Cambio de Preferencias
- **Pregunta Original:** 20. ¿Consideras que tus experiencias sentimentales anteriores han cambiado lo que buscas?
- **Nombre Técnico:** `cambio_por_experiencia`
- **Tipo Estadístico:** Ordinal.
- **Valores Posibles:** Mucho, Algo, Poco, Nada, No he tenido.
- **Transformación:** Mapeo numérico 0 (nada/no he tenido) a 3 (Mucho).

## Tratamiento de Valores Faltantes (General)
- **Variables Ordinales (Likert):** Imputación por la Mediana del subgrupo (ej. por género) o `KNNImputer`.
- **Variables Categóricas (Nominales):** Imputación por la Moda o creación de la categoría "Desconocido".
- **Filtro de Ruido:** Encuestados con más del 30% de valores faltantes serán excluidos del pipeline de Machine Learning (Fase 8).

*Nota: Este diccionario se debe ir actualizando tan pronto el archivo CSV real se posicione en `data/raw/`.*
