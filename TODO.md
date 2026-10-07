# TODO del proyecto

Lista de tareas para completar la reorganizacion y modularizacion del sistema de control y monitorizacion.

## Siguiente paso recomendado

Probar la configuracion local y arrancar los servidores en la maquina de desarrollo o en la Raspberry Pi. La configuracion de red, base de datos, dispositivos y SSH esta centralizada en `src/sctlab/config/settings.py`.

El criterio para dar este paso por terminado es:

- Los valores de `src/sctlab/config/settings.py` son correctos para la maquina de ejecucion.
- `python -m apps.http_server` inicia el servidor sin errores de configuracion.
- La pagina principal carga `frontend/index.html`.
- Los logos y recursos estaticos responden correctamente.
- No se modifica la logica de telemetria ni de comandos.

Una vez superado esto, se puede probar el servidor TCP con el hardware disponible o preparar la seleccion del simulador para desarrollo.

## 1. Preparar el paquete Python

- [x] Crear `__init__.py` en `apps/`, `src/sctlab/` y sus subcarpetas Python.
- [x] Crear un `pyproject.toml` o configurar correctamente `PYTHONPATH` para que `src/sctlab` sea importable.
- [x] Definir el punto de entrada recomendado para iniciar los servidores: `python -m apps.tcp_server`.
- [ ] Documentar los comandos de arranque para desarrollo y produccion.

## 2. Corregir imports y rutas

- [x] Actualizar los imports de `apps/tcp_server.py` a las nuevas rutas de `src/sctlab`.
- [x] Actualizar los imports de los drivers LakeShore, Cryo-Con y del controlador de relaciones.
- [x] Revisar los imports de `apps/http_server.py`; actualmente no usa imports internos del paquete.
- [x] Revisar y actualizar las rutas absolutas usadas para servir `frontend/index.html` y las imagenes.
- [x] Sustituir las rutas y configuraciones dispersas por una configuracion centralizada en `src/sctlab/config/settings.py`.
- [x] Ejecutar una comprobacion de imports sin conectar el hardware.

## 3. Configuracion y seguridad

- [x] Mover host, puertos y direcciones de dispositivos a la configuracion.
- [ ] Mover las credenciales de PostgreSQL fuera del codigo fuente (no necesario para el despliegue local actual).
- [ ] Usar variables de entorno para contrasenas, usuarios y rutas sensibles (no necesario para el despliegue local actual).
- [ ] Crear `.env.example` sin secretos reales (opcional si el sistema se mantiene en una sola maquina).
- [x] Revisar `.gitignore` para excluir secretos, logs, caches y datos generados.
- [ ] Separar configuracion de desarrollo, simulacion y produccion.

## 4. Modularizar el servidor TCP

- [ ] Separar el protocolo TCP de la logica de negocio.
- [ ] Crear un parser para comandos recibidos.
- [ ] Crear un modulo para serializar y parsear mensajes de telemetria.
- [ ] Extraer la gestion de clientes suscritos.
- [ ] Extraer el bucle de adquisicion del LakeShore.
- [ ] Extraer el bucle de adquisicion del Cryo-Con.
- [ ] Extraer la gestion de canales y parametros.
- [ ] Centralizar la gestion del estado de los dispositivos.
- [ ] Reducir el uso de variables globales.
- [ ] Mantener `apps/tcp_server.py` como punto de entrada y coordinacion.

## 5. Modularizar la persistencia

- [ ] Mantener toda la logica PostgreSQL dentro de `src/sctlab/persistence/`.
- [ ] Separar el pool de conexiones en un modulo propio.
- [ ] Crear un repositorio para RUNs.
- [ ] Crear un repositorio para mediciones.
- [ ] Crear un repositorio para archivos de relaciones.
- [ ] Eliminar duplicaciones de logica de base de datos.
- [ ] Revisar transacciones, rollback y devolucion de conexiones al pool.
- [ ] Comprobar indices y permisos definidos en `database/schema/001_initial_schema.sql`.

## 6. Modularizar relaciones experimentales

- [ ] Definir un modelo de estado para una relacion.
- [ ] Separar los modos MANUAL, RAMP y STEP_RAMP.
- [ ] Centralizar validacion de canales, setpoints y velocidades.
- [ ] Separar el almacenamiento de puntos de la ejecucion del controlador.
- [ ] Gestionar correctamente cancelacion, errores y restauracion del estado MXC.
- [ ] Crear pruebas unitarias para `step_ramp.py`.

## 7. Modularizar el servidor HTTP

- [ ] Separar los handlers HTTP de la logica de negocio.
- [ ] Crear un modulo de endpoints.
- [ ] Separar el cliente TCP suscrito.
- [ ] Separar el buffer temporal de temperaturas.
- [ ] Crear funciones independientes para construir respuestas JSON.
- [x] Servir los recursos del frontend usando rutas relativas al proyecto.
- [ ] Mantener `apps/http_server.py` como punto de entrada.

## 8. Modularizar el frontend

- [x] Extraer completamente los estilos inline a `frontend/css/`.
- [x] Separar layout, controles, graficas y tema en archivos CSS (`theme.css`, `layout.css`, `controls.css`, `charts.css`, `relations.css` y `style.css` como bundle).
- [x] Extraer la logica JavaScript a `frontend/js/`.
- [x] Crear `api.js` para las peticiones HTTP.
- [x] Crear `state.js` para el estado de la interfaz.
- [x] Crear `charts.js` para Chart.js y los buffers.
- [x] Crear `controls.js` para canales, switches y parametros de sensores.
- [x] Crear `business.js` para RUNs y relaciones resistencia-temperatura.
- [x] Crear `particles.js` para la animacion de fondo.
- [x] Crear `main.js` para la inicializacion general y la actualizacion de telemetria.
- [ ] Validar en navegador que los modulos cargados funcionan conjuntamente.
- [ ] Revisar `frontend/js/script.js` y eliminarlo cuando la version modular este validada.
- [ ] Revisar los textos, unidades y nombres de variables de la interfaz.

## 9. Drivers y simulacion

- [ ] Definir una interfaz comun para el LakeShore real y el dummy.
- [ ] Permitir seleccionar hardware real o simulador mediante configuracion.
- [ ] Evitar que el codigo de aplicacion dependa directamente de PyVISA.
- [ ] Revisar manejo de desconexiones y reconexiones.
- [ ] Revisar timeouts, bloqueos y limites de frecuencia de comunicacion.
- [ ] Mantener las pruebas de hardware separadas de las pruebas automaticas.

## 10. Pruebas

- [ ] Crear pruebas unitarias para parsers y serializadores TCP.
- [ ] Crear pruebas unitarias para validacion de comandos.
- [ ] Crear pruebas unitarias para la base de datos usando mocks.
- [ ] Crear pruebas unitarias para el LakeShore dummy.
- [ ] Crear pruebas unitarias para relaciones y rampas.
- [ ] Crear pruebas de integracion del servidor TCP.
- [ ] Crear pruebas de integracion del servidor HTTP.
- [ ] Ejecutar `tests/hardware/test_lakeshore_connection.py` solo con hardware disponible.
- [ ] Marcar claramente las pruebas que requieren PostgreSQL.
- [ ] Crear una comprobacion automatica que verifique que los servidores arrancan.

## 11. Documentacion y despliegue

- [ ] Actualizar `README.md` con la estructura y los comandos reales de arranque.
- [ ] Documentar el protocolo TCP.
- [ ] Documentar los endpoints HTTP.
- [ ] Documentar la configuracion del hardware.
- [ ] Documentar la configuracion de PostgreSQL.
- [ ] Documentar los modos de simulacion y desarrollo.
- [ ] Crear instrucciones de despliegue en la Raspberry Pi.
- [ ] Crear servicios de arranque para el servidor TCP, HTTP y SSH Guardian.
- [ ] Documentar logs, puertos y comprobaciones de salud.

## 12. Validacion final

- [ ] Arrancar el servidor TCP usando el simulador.
- [ ] Arrancar el servidor HTTP.
- [ ] Abrir la interfaz web y comprobar que carga los recursos.
- [ ] Comprobar la recepcion de telemetria.
- [ ] Comprobar el envio de comandos desde el frontend.
- [ ] Comprobar inicio y finalizacion de RUNs.
- [ ] Comprobar relaciones MANUAL, RAMP y STEP_RAMP.
- [ ] Comprobar guardado y recuperacion de datos desde PostgreSQL.
- [ ] Ejecutar todas las pruebas automaticas.
- [ ] Revisar que no quedan imports ni rutas antiguas.
- [ ] Revisar que no hay credenciales ni datos sensibles en el repositorio.
