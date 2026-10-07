# Estructura del proyecto

Este documento describe la organizacion del sistema de control y monitorizacion del LakeShore 370, el controlador Cryo-Con y los experimentos de relacion resistencia-temperatura.

La estructura separa los puntos de entrada, la logica Python, el frontend, las pruebas, la base de datos, los scripts auxiliares y la documentacion.

## Arbol general

```text
TCP_SERVER_CAB/
|
|-- apps/
|   |-- tcp_server.py
|   |-- http_server.py
|   `-- ssh_guardian.py
|
|-- src/
|   `-- sctlab/
|       |-- config/
|       |   |-- defaults.py
|       |   `-- colors.py
|       |-- domain/
|       |-- hardware/
|       |   |-- lakeshore370.py
|       |   |-- lakeshore370_dummy.py
|       |   `-- bbcon.py
|       |-- services/
|       |-- relations/
|       |   `-- step_ramp.py
|       |-- transport/
|       |-- persistence/
|       |   `-- database.py
|       |-- web/
|       `-- security/
|
|-- frontend/
|   |-- index.html
|   |-- css/
|   |   |-- theme.css
|   |   |-- layout.css
|   |   |-- controls.css
|   |   |-- charts.css
|   |   |-- relations.css
|   |   `-- style.css (bundle import)
|   |-- js/
|   |   |-- state.js
|   |   |-- api.js
|   |   |-- ui.js
|   |   |-- charts.js
|   |   |-- controls.js
|   |   |-- business.js
|   |   |-- particles.js
|   |   |-- main.js
|   |   `-- script.js (referencia no cargada)
|   `-- assets/
|       |-- SCTLab_logo.png
|       `-- logoCAB.png
|
|-- tests/
|   |-- unit/
|   |-- integration/
|   `-- hardware/
|       |-- test_lakeshore_connection.py
|       `-- test_lakeshore_connection.py.save
|
|-- database/
|   |-- schema/
|   |   `-- 001_initial_schema.sql
|   `-- queries/
|
|-- scripts/
|   `-- cliente_test.py
|
|-- docs/
|   |-- README_estructura.md
|   |-- 370_manual.pdf
|   `-- ESQUEMA.jpg
|
|-- README.md
`-- .gitignore
```

## `apps/`

Contiene los puntos de entrada de los procesos de la aplicacion. Estos archivos coordinan los componentes de `src/sctlab`, pero la logica reutilizable debe mantenerse fuera de esta carpeta.

### `apps/tcp_server.py`

Inicia el servidor TCP que se comunica con los clientes y con los instrumentos. Gestiona las conexiones, recibe comandos, publica telemetria y coordina la adquisicion del LakeShore y del Cryo-Con.

Tambien integra las operaciones de RUN, los comandos de configuracion y las relaciones experimentales.

### `apps/http_server.py`

Inicia el servidor HTTP que sirve la interfaz web y expone los endpoints utilizados por el navegador.

Se encarga de entregar datos actuales, recibir comandos enviados desde el frontend, mantener la suscripcion TCP de telemetria y proporcionar datos historicos y graficas.

### `apps/ssh_guardian.py`

Inicia el proceso de supervision de accesos SSH. Controla las IP autorizadas, la lista blanca, las IP temporales y la expiracion de autorizaciones.

## `src/sctlab/`

Es el paquete principal de Python. Contiene el codigo reutilizable y se divide por responsabilidades.

Cada subcarpeta debe incluir modulos Python relacionados con una misma responsabilidad y, cuando sea necesario, un archivo `__init__.py` para definir el paquete.

## `src/sctlab/config/`

Contiene constantes, valores por defecto y configuracion compartida.

### `src/sctlab/config/defaults.py`

Define la configuracion inicial del sistema: canales activos, ajustes PID, rangos de excitacion, curvas de sensores, setpoints, rangos del heater, parametros del Cryo-Con y frecuencia de insercion en la base de datos.

Los secretos, contraseñas y direcciones dependientes del entorno deben configurarse mediante variables de entorno o ficheros de configuracion externos.

### `src/sctlab/config/colors.py`

Define codigos y constantes de colores para los mensajes de consola y los registros del servidor.

## `src/sctlab/domain/`

Contiene los modelos y conceptos propios del dominio experimental, sin depender directamente de sockets, PyVISA, HTTP o PostgreSQL.

Debe incluir elementos como:

- Mediciones de temperatura, resistencia y potencia.
- Estado de los canales.
- Estado de un RUN.
- Estado de una relacion resistencia-temperatura.
- Identificadores y tipos de canal.

Esta carpeta esta preparada para contener la logica y los modelos que permitan evitar el uso excesivo de variables globales.

## `src/sctlab/hardware/`

Contiene los drivers y simuladores de los instrumentos.

### `src/sctlab/hardware/lakeshore370.py`

Driver del controlador LakeShore 370 real. Usa PyVISA para abrir la comunicacion serie, consultar temperaturas y resistencias, configurar canales, leer parametros y controlar el heater.

### `src/sctlab/hardware/lakeshore370_dummy.py`

Simulador compatible con la interfaz del LakeShore 370. Genera valores de temperatura, resistencia y potencia sin necesidad de conectar el instrumento fisico.

Se utiliza para desarrollo, pruebas y demostraciones.

### `src/sctlab/hardware/bbcon.py`

Driver del controlador de cuerpo negro Cryo-Con Model 32. Gestiona la comunicacion VISA, las consultas de temperatura, setpoint, potencia, rango del heater y parametros PID.

## `src/sctlab/services/`

Contiene los casos de uso de la aplicacion y la logica que coordina varias partes del sistema.

Debe incluir servicios como:

- Adquisicion y procesamiento de telemetria.
- Ejecucion y validacion de comandos.
- Gestion de canales y parametros.
- Inicio, parada y recuperacion de RUNs.
- Coordinacion de los dispositivos hardware.
- Gestion de relaciones resistencia-temperatura.

Los servicios reciben dependencias de hardware, persistencia y transporte en lugar de crear conexiones globales directamente.

## `src/sctlab/relations/`

Contiene los controladores de los experimentos que relacionan la temperatura del MXC con la resistencia de otro canal.

### `src/sctlab/relations/step_ramp.py`

Implementa el controlador asincrono de relaciones mediante una secuencia de escalones de temperatura. Gestiona la preparacion, estabilizacion, medida, almacenamiento de puntos y finalizacion del experimento.

## `src/sctlab/transport/`

Contiene la comunicacion entre el servidor y sus clientes.

Debe incluir:

- Protocolo de mensajes TCP.
- Modo de suscripcion de telemetria.
- Modo de ejecucion de comandos.
- Parseo y serializacion de mensajes.
- Gestion de clientes conectados.

La capa de transporte no debe contener logica especifica de PyVISA ni consultas SQL.

## `src/sctlab/persistence/`

Contiene el acceso a los sistemas de almacenamiento persistente.

### `src/sctlab/persistence/database.py`

Gestiona el pool de conexiones PostgreSQL y las operaciones relacionadas con RUNs y relaciones experimentales.

Debe centralizar:

- Apertura y cierre del pool.
- Conexion segura a la base de datos.
- Inicio, finalizacion y recuperacion de RUNs.
- Guardado de mediciones.
- Guardado y consulta de archivos de relaciones.

## `src/sctlab/web/`

Contiene los componentes reutilizables de la capa HTTP.

Debe incluir, de forma separada:

- Handlers HTTP.
- Definicion de endpoints.
- Construccion de respuestas JSON.
- Buffer temporal de telemetria.
- Cliente TCP suscrito usado por el servidor HTTP.
- Funciones para servir recursos estaticos.

El arranque del servidor permanece en `apps/http_server.py`.

## `src/sctlab/security/`

Contiene la logica reutilizable relacionada con autenticacion, autorizacion, listas blancas y control de accesos.

La ejecucion del vigilante SSH se realiza desde `apps/ssh_guardian.py`.

## `frontend/`

Contiene todos los recursos enviados al navegador.

### `frontend/index.html`

Define la estructura de la interfaz web: pestañas de control, paneles del LakeShore, controles del Cryo-Con, grafica de relaciones, controles de RUN y registros del sistema.

El documento debe contener principalmente HTML y referencias a las hojas de estilo y scripts externos.

### `frontend/css/`

Contiene los estilos CSS de la interfaz.

Se organiza de forma modular en:

- `theme.css`: colores, tipografía, canvas de partículas, indicadores y utilidades generales.
- `layout.css`: distribución general, cabecera superior, navegación por pestañas y paneles.
- `controls.css`: botones, entradas, selectores, switches, dropdowns, barra MXC y barras de progreso.
- `charts.css`: tamaños de gráficas, canvas, mini-gráfica MXC y registros (logs).
- `relations.css`: paneles, controles y reconstrucción de la pestaña Resistance vs. TMXC.
- `style.css`: hoja maestra que importa todos los módulos anteriores mediante `@import`.

### `frontend/js/`

Contiene la logica JavaScript del cliente web.

La aplicacion carga actualmente estos modulos desde `frontend/index.html`, en este orden:

- `api.js`: peticiones HTTP a la API.
- `state.js`: estado local de la interfaz.
- `ui.js`: registros, secciones colapsables, valores mostrados, etapas y pestañas.
- `charts.js`: graficas de temperatura, grafica de relaciones y buffers visuales.
- `controls.js`: canales, switches, parametros de sensores y comandos de configuracion.
- `business.js`: control de RUNs y relaciones resistencia-temperatura.
- `particles.js`: animacion de fondo.
- `main.js`: inicializacion general y actualizacion periodica de telemetria.

### `frontend/js/script.js`

Conserva la implementacion monolitica original como referencia durante la migracion. No se carga desde `index.html`; debe eliminarse solo despues de validar completamente la version modular.

### `frontend/assets/`

Contiene imagenes y recursos estaticos utilizados por la interfaz.

- `SCTLab_logo.png`: logotipo mostrado en la cabecera de la aplicacion.
- `logoCAB.png`: logotipo del Centro de Astrobiologia utilizado en la documentacion.

## `tests/`

Contiene las pruebas del sistema, separadas segun el nivel de dependencia.

### `tests/unit/`

Pruebas de funciones, modelos, parsers, validadores y controladores que no necesitan hardware ni servidores activos.

### `tests/integration/`

Pruebas de integracion entre servicios, servidor TCP, servidor HTTP, base de datos y protocolo de comunicaciones.

### `tests/hardware/`

Pruebas que acceden directamente a PyVISA o a un instrumento fisico.

#### `tests/hardware/test_lakeshore_connection.py`

Realiza comprobaciones manuales de conexion y consulta del LakeShore 370, incluyendo canales, rangos, autoscan, heater y configuracion de resistencia.

Debe ejecutarse solamente cuando el instrumento y el puerto serie esten disponibles.

#### `tests/hardware/test_lakeshore_connection.py.save`

Copia de respaldo de la prueba manual de conexion. No forma parte de la suite automatica y solo debe conservarse como referencia historica si resulta necesario.

## `database/`

Contiene los recursos SQL de PostgreSQL.

### `database/schema/`

Contiene scripts versionados para crear y modificar las tablas, indices, permisos y restricciones de la base de datos.

### `database/schema/001_initial_schema.sql`

Define el esquema inicial para canales, RUNs, mediciones y archivos de relaciones experimentales.

### `database/queries/`

Contiene consultas SQL reutilizables, consultas de mantenimiento y consultas de diagnostico que no forman parte directamente del esquema.

## `scripts/`

Contiene herramientas auxiliares que se ejecutan de forma independiente y no son parte del servidor de produccion.

### `scripts/cliente_test.py`

Cliente TCP sencillo para conectarse al servidor, enviar el comando `SUB` y mostrar por pantalla los mensajes de telemetria recibidos.

## `docs/`

Contiene la documentacion tecnica, manuales, diagramas y referencias del sistema.

### `docs/README_estructura.md`

Describe la organizacion de carpetas y la responsabilidad de cada archivo y modulo.

### `docs/370_manual.pdf`

Manual de referencia del controlador LakeShore 370.

### `docs/ESQUEMA.jpg`

Diagrama o esquema de referencia de la instalacion y sus conexiones.

## Archivos de la raiz

### `README.md`

Documento principal del proyecto. Explica el objetivo del sistema, el flujo general de datos, los componentes principales y las instrucciones basicas de uso.

### `.gitignore`

Define los archivos y carpetas que no deben incluirse en el control de versiones, como caches, entornos virtuales, secretos, logs o ficheros generados.

## Flujo general del sistema

```text
LakeShore 370 / Cryo-Con
          |
          v
     apps/tcp_server.py
          |
          +--> clientes TCP suscritos
          |
          +--> src/sctlab/persistence/database.py
          |
          v
     apps/http_server.py
          |
          v
     frontend/index.html
```

El servidor TCP controla los instrumentos y publica la telemetria. El servidor HTTP se suscribe a esa telemetria, expone una API para el navegador y recibe los comandos enviados desde la interfaz web.
