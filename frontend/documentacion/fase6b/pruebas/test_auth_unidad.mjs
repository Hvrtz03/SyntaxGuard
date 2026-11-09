// Pruebas unitarias de la Fase 6B (js/api.js + js/auth.js + js/state.js) con el ejecutor integrado de Node.
// SIN dependencias: node --test frontend/documentacion/fase6b/pruebas/test_auth_unidad.mjs
// `fetch` está simulado (no hay red ni servidor). Estas pruebas verifican la LÓGICA del cliente según el contrato
// FASE6_CONTRATO_API.md; la integración con el backend real está en probar_interfaz_fase6b.py.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const JS = path.resolve(path.dirname(new URL(import.meta.url).pathname), '../../../js');
const { api, ErrorApi } = await import(pathToFileURL(path.join(JS, 'api.js')));
const { restaurarSesion, iniciarSesion, registrar, cerrarSesion, invalidarSesion } = await import(pathToFileURL(path.join(JS, 'auth.js')));
const { obtener } = await import(pathToFileURL(path.join(JS, 'state.js')));

/* ---------- Valores de prueba (inventados; no son credenciales reales) ---------- */
const CLAVE_PRUEBA = 'clave-de-prueba-9X7q-unitaria';
const CSRF_A = 'a'.repeat(64);
const CSRF_B = 'b'.repeat(64);
const CSRF_C = 'c'.repeat(64);

/* ---------- Vigilantes: storage, cookie y consola ---------- */
const accesosProhibidos = [];
for (const nombre of ['localStorage', 'sessionStorage']) {
  Object.defineProperty(globalThis, nombre, {
    configurable: true,
    get() { accesosProhibidos.push(nombre); throw new Error(`Acceso prohibido a ${nombre}`); },
  });
}
Object.defineProperty(globalThis, 'document', { configurable: true, get() { accesosProhibidos.push('document'); throw new Error('Acceso prohibido a document'); } });
const salidaConsola = [];
for (const m of ['log', 'info', 'warn', 'error', 'debug', 'trace']) {
  console[m] = (...args) => { salidaConsola.push(args.map((a) => { try { return typeof a === 'string' ? a : JSON.stringify(a); } catch { return String(a); } }).join(' ')); };
}
// (el ejecutor de pruebas escribe por otro canal; salidaConsola solo recoge lo que escriba el código bajo prueba)

/* ---------- fetch simulado ---------- */
let llamadas = [];
const json = (estado, cuerpo, cabeceras = {}) => new Response(JSON.stringify(cuerpo), { status: estado, headers: { 'Content-Type': 'application/json', ...cabeceras } });
const sesionOk = (id = 1, csrf = CSRF_A, nombre = 'ana') => ({ usuario: { id, usuario: nombre, creado_en: '2026-11-07T20:15:00Z' }, csrf_token: csrf, sesion: { expira_en: '2026-11-14T20:15:00Z' } });

/** manejador(url, init, n) → Response | Promise<Response>. Si devuelve 'colgar', la petición espera hasta abortarse. */
function instalarFetch(manejador) {
  llamadas = [];
  globalThis.fetch = (url, init = {}) => {
    const cabeceras = {};
    for (const [k, v] of Object.entries(init.headers || {})) cabeceras[k.toLowerCase()] = v;
    const registro = { url, metodo: (init.method || 'GET').toUpperCase(), cabeceras, cuerpo: init.body, credentials: init.credentials, n: llamadas.length };
    llamadas.push(registro);
    const r = manejador(url, init, registro);
    if (r === 'colgar') {
      return new Promise((_, rechazar) => {
        const abortar = () => rechazar(Object.assign(new Error('abortada'), { name: 'AbortError' }));
        if (init.signal?.aborted) abortar(); else init.signal?.addEventListener('abort', abortar, { once: true });
      });
    }
    return Promise.resolve(r);
  };
}
const cuantas = (metodo, ruta) => llamadas.filter((l) => l.metodo === metodo && l.url === ruta).length;

/** Deja el módulo en estado «sin sesión» y sin usuario previo recordado. */
async function reiniciar() {
  instalarFetch(() => json(200, { cerrada: true, habia_sesion: false }));
  await cerrarSesion();
}
async function entrarComo(id = 1, csrf = CSRF_A) {
  instalarFetch(() => json(200, sesionOk(id, csrf)));
  await iniciarSesion('ana', CLAVE_PRUEBA);
}
const sesion = () => obtener().sesion;

/* =========================== Restauración de sesión =========================== */
test('GET /auth/me 200: restaura la sesión, guarda al usuario y usa credentials same-origin', async () => {
  await reiniciar();
  instalarFetch(() => json(200, sesionOk()));
  await restaurarSesion();
  assert.equal(sesion().fase, 'autenticado');
  assert.equal(sesion().usuario.usuario, 'ana');
  assert.deepEqual(Object.keys(sesion().usuario).sort(), ['creado_en', 'id', 'usuario']);
  assert.equal(llamadas.length, 1);
  assert.equal(llamadas[0].url, '/auth/me');
  assert.equal(llamadas[0].metodo, 'GET');
  assert.equal(llamadas[0].credentials, 'same-origin');
  assert.equal('x-csrf-token' in llamadas[0].cabeceras, false, 'un GET no lleva X-CSRF-Token');
});

test('el token CSRF no está en el estado público ni en ninguna parte visible', async () => {
  await reiniciar();
  instalarFetch(() => json(200, sesionOk(1, CSRF_A)));
  await restaurarSesion();
  assert.equal(JSON.stringify(obtener()).includes(CSRF_A), false);
});

test('restaurarSesion es de una sola solicitud aunque se llame varias veces a la vez', async () => {
  await reiniciar();
  instalarFetch(() => json(200, sesionOk()));
  await Promise.all([restaurarSesion(), restaurarSesion(), restaurarSesion()]);
  assert.equal(cuantas('GET', '/auth/me'), 1);
});

test('401 no_autenticado → pantalla de acceso sin aviso; 401 sesion_expirada → con aviso', async () => {
  await reiniciar();
  instalarFetch(() => json(401, { detail: 'Debes iniciar sesión.', codigo: 'no_autenticado' }));
  await restaurarSesion();
  assert.equal(sesion().fase, 'anonimo');
  assert.equal(sesion().aviso, null);
  instalarFetch(() => json(401, { detail: 'Tu sesión expiró o ya no es válida. Inicia sesión de nuevo.', codigo: 'sesion_expirada' }));
  await restaurarSesion();
  assert.equal(sesion().fase, 'anonimo');
  assert.match(sesion().aviso.texto, /Tu sesión expiró/);
});

test('error 500 o de red al arrancar → fase «error» (no se muestra el acceso ni la app)', async () => {
  await reiniciar();
  instalarFetch(() => json(500, { detail: 'Traceback interno secreto' }));
  await restaurarSesion();
  assert.equal(sesion().fase, 'error');
  assert.equal(sesion().detalle.includes('Traceback'), false, 'no se filtran detalles internos');
  instalarFetch(() => { throw new TypeError('fetch failed'); });
  await restaurarSesion();
  assert.equal(sesion().fase, 'error');
  assert.match(sesion().detalle, /No se pudo conectar/);
});

test('respuesta 200 mal formada de /auth/me → fase «error»', async () => {
  await reiniciar();
  instalarFetch(() => json(200, { algo: 'raro' }));
  await restaurarSesion();
  assert.equal(sesion().fase, 'error');
});

test('comprobación silenciosa: un fallo de red no expulsa; un 401 sí', async () => {
  await entrarComo();
  instalarFetch(() => { throw new TypeError('fetch failed'); });
  await restaurarSesion({ silenciosa: true });
  assert.equal(sesion().fase, 'autenticado');
  instalarFetch(() => json(401, { detail: 'x', codigo: 'sesion_expirada' }));
  await restaurarSesion({ silenciosa: true });
  assert.equal(sesion().fase, 'anonimo');
});

/* =========================== Registro e inicio de sesión =========================== */
test('login correcto: JSON {usuario, contrasena}, sesión abierta y el token se envía en los POST privados (no en los GET)', async () => {
  await reiniciar();
  instalarFetch(() => json(200, sesionOk(1, CSRF_A)));
  await iniciarSesion('ana', CLAVE_PRUEBA);
  assert.equal(llamadas[0].url, '/auth/login');
  assert.equal(llamadas[0].metodo, 'POST');
  assert.equal(llamadas[0].cabeceras['content-type'], 'application/json');
  assert.deepEqual(JSON.parse(llamadas[0].cuerpo), { usuario: 'ana', contrasena: CLAVE_PRUEBA });
  assert.equal(sesion().fase, 'autenticado');

  instalarFetch(() => json(200, { es_spam: false, probabilidad: 0.1, rasgos_detectados: [] }));
  await api.predecir({ texto: 'hola' });
  await api.historial({});
  assert.equal(llamadas[0].metodo, 'POST');
  assert.equal(llamadas[0].cabeceras['x-csrf-token'], CSRF_A);
  assert.equal(llamadas[1].metodo, 'GET');
  assert.equal('x-csrf-token' in llamadas[1].cabeceras, false);
  assert.equal(llamadas[0].credentials, 'same-origin');
});

test('DELETE y POST con cuerpo crudo también llevan X-CSRF-Token', async () => {
  await entrarComo(1, CSRF_A);
  instalarFetch(() => json(200, { eliminados: 1 }));
  await api.eliminarAnalisis(5);
  await api.extraerCorreo({ datos: new Uint8Array([65, 66]), nombre: 'a.eml' });
  assert.equal(llamadas[0].metodo, 'DELETE');
  assert.equal(llamadas[0].cabeceras['x-csrf-token'], CSRF_A);
  assert.equal(llamadas[1].cabeceras['x-csrf-token'], CSRF_A);
  assert.equal(llamadas[1].cabeceras['content-type'], 'message/rfc822');
});

test('login 401 credenciales_invalidas: mensaje del contrato, NO cuenta como sesión expirada ni cancela nada', async () => {
  await reiniciar();
  instalarFetch(() => json(401, { detail: 'Usuario o contraseña incorrectos.', codigo: 'credenciales_invalidas' }));
  await assert.rejects(() => iniciarSesion('ana', CLAVE_PRUEBA), (e) => {
    assert.ok(e instanceof ErrorApi);
    assert.equal(e.codigo, 'credenciales_invalidas');
    assert.equal(e.estado, 401);
    assert.equal(e.message, 'Usuario o contraseña incorrectos.');
    assert.equal(e.detalle, null, 'el cuerpo de las respuestas /auth/* no se conserva');
    return true;
  });
  assert.equal(sesion().fase, 'anonimo');
  assert.doesNotMatch(sesion().aviso?.texto ?? '', /expir/i, 'no se muestra «Tu sesión expiró» por un login fallido');
});

test('login 429: reintentarEn y mensaje con la espera', async () => {
  await reiniciar();
  instalarFetch(() => json(429, { detail: 'Demasiados intentos fallidos. Espera antes de volver a intentar.', codigo: 'demasiados_intentos', reintentar_en_segundos: 900 }, { 'Retry-After': '900' }));
  await assert.rejects(() => iniciarSesion('ana', CLAVE_PRUEBA), (e) => {
    assert.equal(e.codigo, 'demasiados_intentos');
    assert.equal(e.reintentarEn, 900);
    assert.match(e.message, /15 min/);
    return true;
  });
});

test('429 con solo la cabecera Retry-After también informa la espera', async () => {
  await reiniciar();
  instalarFetch(() => json(429, { detail: 'Demasiados intentos fallidos. Espera antes de volver a intentar.', codigo: 'demasiados_intentos' }, { 'Retry-After': '45' }));
  await assert.rejects(() => iniciarSesion('ana', CLAVE_PRUEBA), (e) => e.reintentarEn === 45 && /45 s/.test(e.message));
});

test('registro 422 conserva `campos`; registro 409 marca el campo usuario', async () => {
  await reiniciar();
  const campos = { usuario: 'El usuario debe tener de 3 a 32 caracteres: letras minúsculas sin acento, números, punto, guion o guion bajo, y empezar con letra o número.', contrasena: 'La contraseña debe tener al menos 10 caracteres.' };
  instalarFetch(() => json(422, { detail: 'Los datos de registro no son válidos.', codigo: 'datos_invalidos', campos }));
  await assert.rejects(() => registrar('A', 'corta'), (e) => e.estado === 422 && e.codigo === 'datos_invalidos' && e.campos.contrasena === campos.contrasena);
  assert.equal(llamadas[0].url, '/auth/registro');
  instalarFetch(() => json(409, { detail: 'Ese nombre de usuario ya está en uso.', codigo: 'usuario_duplicado', campos: { usuario: 'Ese nombre de usuario ya está en uso.' } }));
  await assert.rejects(() => registrar('ana', CLAVE_PRUEBA), (e) => e.estado === 409 && e.campos.usuario === 'Ese nombre de usuario ya está en uso.');
  assert.equal(sesion().fase, 'anonimo');
});

test('registro 201 abre sesión', async () => {
  await reiniciar();
  instalarFetch(() => json(201, sesionOk(7, CSRF_B, 'nuevo')));
  await registrar('nuevo', CLAVE_PRUEBA);
  assert.equal(sesion().fase, 'autenticado');
  assert.equal(sesion().usuario.usuario, 'nuevo');
});

test('403 origen_no_permitido y 5xx en /auth/*: mensajes amables, sin detalles técnicos', async () => {
  await reiniciar();
  instalarFetch(() => json(403, { detail: 'Falta el encabezado Origin (o es inválido).', codigo: 'origen_no_permitido' }));
  await assert.rejects(() => iniciarSesion('ana', CLAVE_PRUEBA), (e) => !/Origin/.test(e.message) && /seguridad/.test(e.message));
  instalarFetch(() => json(500, { detail: 'sqlite3.OperationalError: tabla secreta' }));
  await assert.rejects(() => iniciarSesion('ana', CLAVE_PRUEBA), (e) => !/sqlite/.test(e.message));
});

test('200 mal formado en login no abre sesión', async () => {
  await reiniciar();
  instalarFetch(() => json(200, { usuario: null }));
  await assert.rejects(() => iniciarSesion('ana', CLAVE_PRUEBA), ErrorApi);
  assert.equal(sesion().fase, 'anonimo');
});

/* =========================== 401 en endpoints privados =========================== */
test('401 en un endpoint privado: borra la sesión y el token, avisa y cancela las peticiones pendientes', async () => {
  await entrarComo(1, CSRF_A);
  instalarFetch((url) => (url === '/historial' ? 'colgar' : json(401, { detail: 'Tu sesión expiró o ya no es válida. Inicia sesión de nuevo.', codigo: 'sesion_expirada' })));
  const pendiente = api.historial({}).catch((e) => e);
  await assert.rejects(() => api.predecir({ texto: 'x' }), (e) => e instanceof ErrorApi && e.tipo === 'sesion');
  const errPendiente = await pendiente;
  assert.ok(errPendiente instanceof ErrorApi);
  assert.equal(errPendiente.tipo, 'sesion', 'la petición pendiente se cancela como sesión terminada');
  assert.equal(sesion().fase, 'anonimo');
  assert.match(sesion().aviso.texto, /Tu sesión expiró\. Inicia sesión de nuevo\./);
  assert.equal(sesion().usuario, null);
  // el token ya no se envía
  instalarFetch(() => json(401, { detail: 'x', codigo: 'no_autenticado' }));
  await api.predecir({ texto: 'otra' }).catch(() => {});
  assert.equal('x-csrf-token' in llamadas[0].cabeceras, false);
});

test('invalidarSesion es idempotente', async () => {
  await entrarComo();
  invalidarSesion('expirada');
  const primero = sesion();
  invalidarSesion('expirada');
  assert.equal(sesion(), primero, 'la segunda llamada no vuelve a publicar estado');
});

test('429 en un endpoint privado: no se reintenta y se informa la espera', async () => {
  await entrarComo();
  instalarFetch(() => json(429, { detail: 'Demasiadas solicitudes.', codigo: 'demasiados_intentos', reintentar_en_segundos: 30 }));
  await assert.rejects(() => api.predecir({ texto: 'x' }), (e) => e.estado === 429 && /30 s/.test(e.message));
  assert.equal(llamadas.length, 1);
  assert.equal(sesion().fase, 'autenticado');
});

/* =========================== CSRF: 403 csrf_invalido =========================== */
test('403 csrf_invalido: una sola llamada a /auth/me y UN reintento con el token nuevo', async () => {
  await entrarComo(1, CSRF_A);
  let intentos = 0;
  instalarFetch((url, init, reg) => {
    if (url === '/auth/me') return json(200, sesionOk(1, CSRF_B));
    intentos++;
    return reg.cabeceras['x-csrf-token'] === CSRF_B ? json(200, { es_spam: true, probabilidad: 0.9, rasgos_detectados: [] }) : json(403, { detail: 'Falta el token CSRF o no es válido.', codigo: 'csrf_invalido' });
  });
  const r = await api.predecir({ texto: 'x' });
  assert.equal(r.es_spam, true);
  assert.equal(cuantas('GET', '/auth/me'), 1);
  assert.equal(intentos, 2);
  assert.equal(llamadas.filter((l) => l.url === '/predecir')[1].cabeceras['x-csrf-token'], CSRF_B);
  assert.equal(sesion().fase, 'autenticado');
});

test('si el reintento también da 403 no hay un tercer intento ni bucle', async () => {
  await entrarComo(1, CSRF_A);
  instalarFetch((url) => (url === '/auth/me' ? json(200, sesionOk(1, CSRF_B)) : json(403, { detail: 'Falta el token CSRF o no es válido.', codigo: 'csrf_invalido' })));
  await assert.rejects(() => api.predecir({ texto: 'x' }), (e) => e.estado === 403 && e.codigo === 'csrf_invalido' && /seguridad/.test(e.message));
  assert.equal(cuantas('POST', '/predecir'), 2);
  assert.equal(cuantas('GET', '/auth/me'), 1);
});

test('varias peticiones con 403 csrf_invalido simultáneas comparten UNA renovación', async () => {
  await entrarComo(1, CSRF_A);
  instalarFetch((url, init, reg) => {
    if (url === '/auth/me') return json(200, sesionOk(1, CSRF_C));
    return reg.cabeceras['x-csrf-token'] === CSRF_C ? json(200, { eliminados: 1 }) : json(403, { detail: 'x', codigo: 'csrf_invalido' });
  });
  await Promise.all([api.eliminarAnalisisVarios([1]), api.eliminarAnalisisVarios([2]), api.eliminarAnalisis(3)]);
  assert.equal(cuantas('GET', '/auth/me'), 1);
});

test('403 csrf_invalido y /auth/me responde 401: sesión terminada, sin reintento', async () => {
  await entrarComo(1, CSRF_A);
  instalarFetch((url) => (url === '/auth/me' ? json(401, { detail: 'x', codigo: 'sesion_expirada' }) : json(403, { detail: 'x', codigo: 'csrf_invalido' })));
  await assert.rejects(() => api.predecir({ texto: 'x' }), (e) => e.tipo === 'sesion');
  assert.equal(cuantas('POST', '/predecir'), 1);
  assert.equal(sesion().fase, 'anonimo');
});

test('403 csrf_invalido y /auth/me responde OTRA cuenta: no se reintenta y se marca cambio de usuario', async () => {
  await entrarComo(1, CSRF_A);
  instalarFetch((url) => (url === '/auth/me' ? json(200, sesionOk(2, CSRF_B, 'otro')) : json(403, { detail: 'x', codigo: 'csrf_invalido' })));
  await assert.rejects(() => api.predecir({ texto: 'x' }), (e) => e.tipo === 'sesion');
  assert.equal(cuantas('POST', '/predecir'), 1, 'la acción NO se repite con la otra cuenta');
  assert.equal(sesion().cambioDeUsuario, true);
});

test('/auth/me responde con otra cuenta al comprobar en segundo plano → cambio de usuario', async () => {
  await entrarComo(1, CSRF_A);
  instalarFetch(() => json(200, sesionOk(2, CSRF_B, 'otro')));
  await restaurarSesion({ silenciosa: true });
  assert.equal(sesion().cambioDeUsuario, true);
});

/* =========================== Cierre de sesión =========================== */
test('logout: POST con X-CSRF-Token, limpia usuario y token', async () => {
  await entrarComo(1, CSRF_A);
  instalarFetch(() => json(200, { cerrada: true, habia_sesion: true }));
  await cerrarSesion();
  assert.equal(llamadas[0].url, '/auth/logout');
  assert.equal(llamadas[0].metodo, 'POST');
  assert.equal(llamadas[0].cabeceras['x-csrf-token'], CSRF_A);
  assert.equal(sesion().fase, 'anonimo');
  assert.equal(sesion().usuario, null);
  instalarFetch(() => json(401, { detail: 'x', codigo: 'no_autenticado' }));
  await api.predecir({ texto: 'x' }).catch(() => {});
  assert.equal('x-csrf-token' in llamadas[0].cabeceras, false, 'el token se borró de la memoria');
});

test('logout sin red: NO se simula el cierre (la sesión sigue viva en el servidor)', async () => {
  await entrarComo(1, CSRF_A);
  instalarFetch(() => { throw new TypeError('fetch failed'); });
  await assert.rejects(() => cerrarSesion(), (e) => e instanceof ErrorApi && e.tipo === 'red');
  assert.equal(sesion().fase, 'autenticado');
  instalarFetch(() => json(200, { es_spam: false, probabilidad: 0, rasgos_detectados: [] }));
  await api.predecir({ texto: 'x' });
  assert.equal(llamadas[0].cabeceras['x-csrf-token'], CSRF_A, 'el token se conserva');
});

test('logout con 403 csrf_invalido: renueva el token una vez y reintenta', async () => {
  await entrarComo(1, CSRF_A);
  instalarFetch((url, init, reg) => {
    if (url === '/auth/me') return json(200, sesionOk(1, CSRF_B));
    return reg.cabeceras['x-csrf-token'] === CSRF_B ? json(200, { cerrada: true, habia_sesion: true }) : json(403, { detail: 'x', codigo: 'csrf_invalido' });
  });
  await cerrarSesion();
  assert.equal(cuantas('POST', '/auth/logout'), 2);
  assert.equal(sesion().fase, 'anonimo');
});

/* =========================== Higiene =========================== */
test('no se tocó localStorage, sessionStorage ni document (cookie) en ninguna prueba', () => {
  assert.deepEqual(accesosProhibidos, []);
});

test('la consola no recibió contraseñas ni tokens CSRF', () => {
  const todo = salidaConsola.join('\n');
  for (const secreto of [CLAVE_PRUEBA, CSRF_A, CSRF_B, CSRF_C]) assert.equal(todo.includes(secreto), false);
});
