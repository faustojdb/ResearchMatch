# RESEARCH MATCH
## Plataforma de Matching Colaborativo para Investigación
### Especificación Técnica y Funcional — Versión 1.0 — Febrero 2026

> **CONFIDENCIAL** — Este documento contiene información propietaria y confidencial.

---

## 1. Visión General

Research Match es una plataforma diseñada para conectar investigadores, científicos, desarrolladores y teóricos independientes que trabajan en problemas similares pero de forma aislada. El concepto central es un sistema de matching inteligente, impulsado por IA, que no solo identifica coincidencias temáticas, sino que evalúa y cuantifica el grado de originalidad y complementariedad entre participantes.

La plataforma resuelve un problema crítico: miles de personas en el mundo trabajan independientemente en la cura del cáncer, en teorías físicas específicas, en el desarrollo de proteínas, en modelos matemáticos avanzados, sin saber que existen entre sí. Research Match las encuentra, las evalúa y las conecta de forma segura.

### 1.1 Principios Fundamentales

1. **Blindaje total de propiedad intelectual:** la información de cada usuario está cifrada y es inaccesible para otros usuarios, para la plataforma y para terceros. Solo la IA evalúa el contenido en entornos aislados.
2. **Matching por complementariedad, no por duplicación:** el sistema prioriza perfiles que se potencian mutuamente sobre perfiles idénticos.
3. **Conveniencia bilateral:** todo match se evalúa desde ambas perspectivas. Ningún usuario es expuesto a relaciones parasitarias.
4. **Transparencia en la evaluación:** cada usuario puede ver sus propios scores y entender cómo fueron calculados, pero nunca los detalles del trabajo de otro usuario.
5. **Licenciamiento conjunto:** cuando dos o más usuarios deciden colaborar, la plataforma facilita la creación de repositorios compartidos bajo licencias que protegen la contribución de cada parte.

---

## 2. Arquitectura de Seguridad y Blindaje de Datos

La seguridad no es una feature de Research Match. Es la condición de existencia de la plataforma. Sin garantías absolutas de que la propiedad intelectual de cada usuario está protegida, el sistema no tiene razón de ser.

### 2.1 Principio de Zero-Knowledge

La plataforma opera bajo un modelo de conocimiento cero (zero-knowledge). Esto significa que ningún actor — incluyendo los administradores del sistema, los otros usuarios, la propia empresa operadora y cualquier tercero — puede acceder al contenido real del trabajo de un usuario. La IA que evalúa la originalidad opera en entornos de ejecución aislados (enclaves seguros) que procesan datos cifrados y solo emiten scores numéricos, nunca el contenido en sí.

### 2.2 Capas de Protección

| Capa | Mecanismo | Protección |
|------|-----------|------------|
| Cifrado en reposo | AES-256 con claves derivadas del usuario | Los datos almacenados son ilegibles sin la clave del propietario |
| Cifrado en tránsito | TLS 1.3 + Certificate Pinning | Toda comunicación es cifrada punto a punto |
| Cifrado homomórfico | Evaluación sobre datos cifrados | La IA calcula scores sin descifrar el contenido original |
| Enclaves seguros (TEE) | Intel SGX / ARM TrustZone | El código de evaluación corre en hardware aislado e inauditable |
| Fragmentación de datos | Sharding criptográfico distribuido | Ningún servidor tiene el dataset completo de un usuario |
| Auditoría inmutable | Blockchain privada / Merkle Trees | Todo acceso queda registrado y es verificable por el usuario |
| Anonimización de perfiles | Identidades pseudonímicas hasta consentimiento | Ningún usuario ve la identidad real de otro hasta que ambos aceptan |

### 2.3 Flujo de Seguridad del Research Commit

**Paso 1 — Cifrado local:** el usuario redacta su Research Commit en el cliente. Antes de enviarse, se cifra localmente con su clave personal. El servidor nunca recibe texto plano.

**Paso 2 — Procesamiento en enclave:** el commit cifrado se envía al enclave seguro. Dentro del enclave, se descifra temporalmente, se analiza, se generan los scores de originalidad, y se destruye la copia descifrada.

**Paso 3 — Almacenamiento fragmentado:** el commit cifrado se fragmenta y distribuye entre múltiples nodos. Ningún nodo individual puede reconstruir el documento.

**Paso 4 — Emisión de scores:** solo los scores numéricos (originalidad teórica, formal-computacional) salen del enclave. Estos scores se vinculan al perfil pseudonímico del usuario.

### 2.4 Garantías para el Usuario

Cada usuario tiene derecho a: revocar el acceso a sus datos en cualquier momento y de forma irreversible (borrado criptográfico); auditar qué procesos han accedido a sus datos y cuándo; exportar toda su información en formato cifrado; verificar la integridad de sus datos mediante pruebas criptográficas; y recibir notificación inmediata ante cualquier intento de acceso no autorizado.

---

## 3. El Research Commit: Estructura Estándar

El Research Commit es la unidad fundamental de información en Research Match. Es el mecanismo mediante el cual cada usuario describe, estructura y somete su trabajo para evaluación. El formato es estandarizado para permitir comparación sistemática por parte de la IA.

### 3.1 Componentes del Research Commit

#### 3.1.1 Teoría Base

Es el marco teórico del que parte el investigador. Define el campo, el problema específico que se aborda, las hipótesis de trabajo y las referencias teóricas fundamentales. Este componente es el ancla del matching: dos usuarios con teoría base similar son candidatos a match.

| Campo | Descripción | Ejemplo |
|-------|-------------|---------|
| Dominio | Campo científico o técnico principal | Biología molecular, Física teórica, ML |
| Subdominio | Especialización dentro del dominio | Plegamiento de proteínas, Gravedad cuántica |
| Problema | Pregunta específica que se intenta resolver | ¿Cómo predecir la estructura terciaria de proteínas intrínsecamente desordenadas? |
| Hipótesis | Proposición central del trabajo | Las interacciones electrostáticas locales son suficientes para predecir conformaciones estables |
| Marco teórico | Teorías y autores de referencia | Modelo de Levinthal, Paradoja de Anfinsen, AlphaFold |

#### 3.1.2 Demostraciones (Eje Formal-Computacional)

Este componente abarca todo lo que prueba, implementa o valida la teoría. Es donde el eje de originalidad formal-computacional se mide con mayor precisión. Incluye tres tipos de artefactos:

| Tipo | Descripción | Formatos aceptados |
|------|-------------|-------------------|
| Demostraciones matemáticas | Pruebas formales, derivaciones, modelos analíticos | LaTeX, MathML, PDF, Lean4, Coq |
| Código / Scripts | Implementaciones, simulaciones, análisis computacional | Python, R, Julia, C++, Jupyter, repositorios Git |
| Datos experimentales | Datasets propios, resultados de simulaciones, benchmarks | CSV, HDF5, Parquet, con metadatos estándar |

La IA evalúa: si las demostraciones son originales o replican métodos conocidos; la sofisticación y eficiencia del código; si los resultados computacionales validan efectivamente la teoría; y la calidad y reproducibilidad de los datos.

#### 3.1.3 Contenido Ad Hoc

Es el material original que no proviene de la teoría base establecida. Aquí reside la mayor fuente de originalidad. Puede incluir: conexiones entre campos no relacionados previamente, métodos no convencionales aplicados al problema, intuiciones formalizadas que aún no tienen respaldo completo en la literatura, y resultados preliminares que sugieren líneas nuevas.

La IA trata este contenido como el diferencial de mayor peso al calcular originalidad teórica. Un alto puntaje en contenido ad hoc indica que el usuario aporta perspectivas que no existen en el corpus común.

#### 3.1.4 Cherry-Picking Declarado

Es la sección de transparencia intelectual. El usuario declara explícitamente qué elementos ha tomado de otros trabajos, de dónde los tomó, por qué los seleccionó, y qué modificó respecto al original. Este componente cumple una doble función: permite a la IA no inflar scores atribuyendo originalidad a contenido curado, y establece un registro de honestidad intelectual que construye reputación dentro de la plataforma.

---

## 4. Sistema de Evaluación de Originalidad por IA

La IA es el árbitro central del sistema. Evalúa cada Research Commit en dos ejes independientes y produce scores que alimentan el algoritmo de matching.

### 4.1 Eje 1: Originalidad Teórica (OT)

Mide cuánto del marco conceptual, las hipótesis y el contenido ad hoc del usuario es genuinamente novedoso respecto al corpus existente y al resto de usuarios de la plataforma.

| Factor | Peso | Descripción |
|--------|------|-------------|
| Novedad de hipótesis | 30% | ¿La hipótesis central es original o es una variación menor de hipótesis existentes? |
| Conexiones interdisciplinarias | 25% | ¿El trabajo conecta campos que normalmente no se cruzan? |
| Contenido Ad Hoc | 30% | ¿El material propio aporta perspectivas ausentes en la literatura? |
| Divergencia del corpus | 15% | ¿Cuánto se diferencia del trabajo de otros usuarios con teoría base similar? |

### 4.2 Eje 2: Originalidad Formal-Computacional (OFC)

Mide la sofisticación, originalidad y eficacia de las demostraciones, el código y los artefactos computacionales. Este eje no evalúa solo matemática pura, sino toda forma de demostrar y ejecutar: scripts, simulaciones, pruebas formales, pipelines de datos.

| Factor | Peso | Descripción |
|--------|------|-------------|
| Originalidad del método formal | 25% | ¿Las demostraciones usan enfoques nuevos o replican métodos estándar? |
| Calidad del código | 20% | Eficiencia, claridad, documentación, reproducibilidad del código |
| Poder de validación | 25% | ¿Los artefactos computacionales efectivamente prueban lo que dicen probar? |
| Sofisticación técnica | 15% | Complejidad y elegancia de las soluciones implementadas |
| Cobertura | 15% | ¿Qué porcentaje de la teoría está respaldado por demostraciones? |

### 4.3 Score Compuesto y Perfil de Originalidad

Cada usuario tiene un perfil de originalidad bidimensional. Por ejemplo: OT: 82% / OFC: 45% indica un teórico fuerte con demostraciones básicas. OT: 35% / OFC: 91% indica alguien con aparato formal poderoso sobre teoría convencional. Estos perfiles complementarios son los que generan los matches más valiosos.

---

## 5. Algoritmo de Matching

### 5.1 Proceso de Match

**Fase 1 — Detección de base común:** la IA identifica usuarios cuya Teoría Base tiene alta similitud semántica (mismo dominio, subdominio y problema, o problemas estrechamente relacionados).

**Fase 2 — Cálculo de complementariedad:** para cada par con base común, se calcula la distancia de originalidad. El match ideal maximiza la distancia en al menos un eje (OT o OFC) manteniendo la cercanía en la base.

**Fase 3 — Evaluación bilateral de conveniencia:** se calcula cuánto ganaría cada parte de la colaboración y se asigna el semáforo.

### 5.2 Semáforo de Conveniencia Bilateral

El semáforo no mide si el match es bueno en abstracto. Mide si la colaboración es conveniente para ambas partes simultáneamente.

| Indicador | Condición | Significado |
|-----------|-----------|-------------|
| 🟢 VERDE | Ambos usuarios aportan >40% de originalidad complementaria al otro | Alta conveniencia mutua. Se recomienda solicitar colaboración. |
| 🟡 AMARILLO | Un usuario aporta >40% pero el otro <40% (asimetría >20 puntos) | Conveniencia asimétrica. Funcional, pero requiere negociación de términos. |
| 🔴 ROJO | Ambos aportan <25%, o la superposición es >75% | Baja conveniencia. Alta redundancia o bajo aporte mutuo. |

### 5.3 Protección contra Relaciones Parasitarias

El sistema incluye múltiples mecanismos para evitar que un usuario extraiga valor sin aportar. El semáforo amarillo alerta sobre asimetría antes de cualquier contacto. Los perfiles son pseudonímicos hasta que ambas partes aceptan la solicitud. La solicitud de colaboración muestra el semáforo y los scores relativos, nunca el contenido del otro usuario. Y el sistema de reputación penaliza patrones de solicitudes rechazadas o abandonadas.

---

## 6. Flujo de Colaboración Post-Match

### 6.1 Solicitud de Equipo

Cuando un usuario decide solicitar colaboración, el proceso es: visualiza el semáforo y los scores relativos del candidato (sin ver su contenido); envía solicitud con un mensaje opcional describiendo qué busca; el candidato recibe la solicitud con los mismos datos del semáforo desde su perspectiva; si ambos aceptan, se inicia el proceso de revelación gradual.

### 6.2 Revelación Gradual

La identidad y el contenido no se revelan de golpe. El sistema implementa un protocolo de revelación por fases: primero se comparten resúmenes generados por la IA (sin datos específicos); luego, si ambos confirman interés, se revelan identidades; finalmente, se abre acceso al repositorio compartido bajo los términos de licencia acordados.

### 6.3 Repositorio Conjunto y Licenciamiento

Una vez formado el equipo, la plataforma genera automáticamente un repositorio compartido con control de versiones que registra la contribución de cada parte; una licencia conjunta configurable que establece propiedad proporcional, derechos de uso, y condiciones de publicación; trazabilidad completa que registra qué aportó cada usuario y cuándo; y mecanismos de resolución de conflictos integrados en los términos de la licencia.

---

## 7. Arquitectura Técnica de Alto Nivel

### 7.1 Componentes Principales

| Componente | Función | Tecnología sugerida |
|------------|---------|-------------------|
| Cliente (Web/Desktop) | Interfaz de usuario, cifrado local, redacción de commits | React/Electron + WebCrypto API |
| API Gateway | Autenticación, rate limiting, enrutamiento | Kong / AWS API Gateway |
| Servicio de Commits | Recepción, fragmentación y almacenamiento de commits cifrados | Microservicio (Rust/Go) |
| Motor de IA (Enclave) | Evaluación de originalidad en entorno aislado | TEE + Modelos NLP/ML especializados |
| Servicio de Matching | Algoritmo de matching y cálculo de semáforos | Microservicio (Python) |
| Repositorio Colaborativo | Versionado, licenciamiento, trazabilidad | Git-based + smart contracts |
| Blockchain de Auditoría | Registro inmutable de accesos y transacciones | Hyperledger / cadena privada |
| Key Management Service | Gestión de claves de cifrado de usuarios | HSM + KMS dedicado |

### 7.2 Modelo de Datos Simplificado

Las entidades principales del sistema son: Usuario (identidad cifrada, claves públicas, perfil pseudonímico, scores de originalidad, historial de matches); Research Commit (teoría base, demostraciones, contenido ad hoc, cherry-picking, todo cifrado y fragmentado); Match (par de usuarios, scores de complementariedad, semáforo, estado de solicitud); y Equipo (miembros, repositorio, licencia, registro de contribuciones).

---

## 8. Roadmap Sugerido

| Fase | Alcance | Entregable |
|------|---------|------------|
| Fase 0: Concepto | Validación de la propuesta con investigadores reales | Feedback de 20-50 usuarios potenciales |
| Fase 1: MVP | Commit estructurado + evaluación básica de IA + matching simple | Plataforma funcional con seguridad básica (cifrado E2E) |
| Fase 2: Seguridad avanzada | Enclaves seguros, cifrado homomórfico, fragmentación | Blindaje completo de datos |
| Fase 3: Colaboración | Repositorios conjuntos, licenciamiento automático, revelación gradual | Flujo completo de match a equipo |
| Fase 4: Escala | Optimización de IA, múltiples dominios, API pública | Plataforma abierta a comunidad global |

---

## 9. Glosario

| Término | Definición |
|---------|------------|
| Research Commit | Unidad estandarizada de información que un usuario somete para evaluación |
| Teoría Base | Marco teórico fundamental del que parte un investigador |
| Originalidad Teórica (OT) | Score que mide la novedad conceptual del trabajo de un usuario |
| Originalidad Formal-Computacional (OFC) | Score que mide la sofisticación de demostraciones, código y artefactos |
| Contenido Ad Hoc | Material original que no proviene de la teoría base establecida |
| Cherry-Picking Declarado | Registro transparente de elementos tomados de otros trabajos |
| Semáforo de Conveniencia | Indicador visual (verde/amarillo/rojo) de conveniencia bilateral de un match |
| Enclave Seguro (TEE) | Entorno de ejecución aislado en hardware donde la IA procesa datos cifrados |
| Cifrado Homomórfico | Técnica que permite computar sobre datos cifrados sin descifrarlos |
| Revelación Gradual | Protocolo por fases para compartir información entre usuarios matcheados |
| Zero-Knowledge | Principio por el cual ningún actor puede acceder al contenido real de un usuario |

---

*Fin del Documento — Research Match v1.0*
