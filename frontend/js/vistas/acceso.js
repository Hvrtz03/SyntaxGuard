// Pantalla de acceso (Fase 6B): iniciar sesión y crear cuenta en la misma tarjeta, sin recargar la página.
// No es una ruta del menú: app.js la muestra cuando no hay sesión.
//
// Seguridad:
//   * Todo texto (incluidos los mensajes de la API y el nombre de usuario) se inserta con h() / nodos de texto.
//     No hay innerHTML.
//   * La contraseña solo existe en los <input>: se lee en el momento de enviar, se pasa a auth.js y se vacía al
//     terminar. No se guarda en variables del módulo, en almacenamiento web ni en la consola.
//   * Mostrar/ocultar contraseña solo cambia el `type` del campo; vuelve a «oculta» al enviar y al cambiar de pestaña.
//   * Las reglas de validación las decide el servidor (contrato §2.1). Aquí solo se avisa de campos vacíos y de que
//     las dos contraseñas coincidan (el servidor no ofrece recuperación de contraseña: un error de tecleo bloquearía la cuenta).
import { ErrorApi } from '../api.js';
import { iniciarSesion, registrar } from '../auth.js';
import { obtener } from '../state.js';
import { h, icono, toast } from '../ui.js';

export const meta = { titulo: 'Acceso' };

const TEXTOS = {
  login: {
    titulo: 'Iniciar sesión',
    sub: 'Entra con tu usuario y contraseña. Tus análisis y tu historial son privados de cada cuenta.',
    boton: 'Entrar', enCurso: 'Entrando…',
    cambio: '¿Aún no tienes cuenta?', cambioBoton: 'Crear cuenta',
  },
  registro: {
    titulo: 'Crear cuenta',
    sub: 'Crea una cuenta para guardar tus análisis. Al terminar, la sesión se inicia automáticamente.',
    boton: 'Crear cuenta', enCurso: 'Creando cuenta…',
    cambio: '¿Ya tienes cuenta?', cambioBoton: 'Iniciar sesión',
  },
};

const AYUDA_REGISTRO = [
  'Usuario: de 3 a 32 caracteres con letras minúsculas sin acento, números, punto, guion o guion bajo; debe empezar con letra o número.',
  'Contraseña: de 10 a 128 caracteres. No uses una contraseña muy común ni tu nombre de usuario.',
  'No hay recuperación de contraseña: guárdala en un lugar seguro.',
];

/** 899 → «14:59». */
function fmtCuenta(seg) {
  const s = Math.max(0, Math.ceil(seg));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

/**
 * Devuelve { el, destruir, enfocar }. `aviso`: { tipo: 'aviso' | 'ok', texto } (p. ej. «Tu sesión expiró…»).
 */
export function renderAcceso({ aviso = null, modo = 'login' } = {}) {
  let modoActual = modo === 'registro' ? 'registro' : 'login';
  let enCurso = false;
  const bloqueoHasta = { login: 0, registro: 0 }; // 429: marca de tiempo hasta la que se bloquea el botón de cada modo
  let reloj = null;

  /* ---------- Campos ---------- */
  const campoUsuario = h('input', {
    class: 'campo-in', id: 'acc-usuario', name: 'usuario', type: 'text', autocomplete: 'username', autocapitalize: 'none',
    autocorrect: 'off', spellcheck: 'false', maxlength: '64', required: true, 'aria-describedby': 'acc-err-usuario',
  });
  const campoClave = h('input', {
    class: 'campo-in campo-in--clave', id: 'acc-clave', name: 'contrasena', type: 'password', autocomplete: 'current-password',
    maxlength: '128', required: true, 'aria-describedby': 'acc-err-clave',
  });
  const campoRepite = h('input', {
    class: 'campo-in campo-in--clave', id: 'acc-repite', name: 'repite', type: 'password', autocomplete: 'new-password',
    maxlength: '128', 'aria-describedby': 'acc-err-repite',
  });
  const errUsuario = h('p', { class: 'campo-error', id: 'acc-err-usuario', hidden: true });
  const errClave = h('p', { class: 'campo-error', id: 'acc-err-clave', hidden: true });
  const errRepite = h('p', { class: 'campo-error', id: 'acc-err-repite', hidden: true });

  const botonOjo = h('button', { type: 'button', class: 'campo-ojo', 'aria-pressed': 'false', 'aria-controls': 'acc-clave acc-repite' });
  let visible = false;
  function pintarOjo() {
    botonOjo.setAttribute('aria-pressed', String(visible));
    botonOjo.setAttribute('aria-label', visible ? 'Ocultar contraseña' : 'Mostrar contraseña');
    botonOjo.setAttribute('title', visible ? 'Ocultar contraseña' : 'Mostrar contraseña');
    botonOjo.replaceChildren(icono(visible ? 'ojoTachado' : 'ojo', { tam: 18 }));
    const tipo = visible ? 'text' : 'password';
    campoClave.type = tipo;
    campoRepite.type = tipo;
  }
  botonOjo.addEventListener('click', () => { visible = !visible; pintarOjo(); });

  const filaRepite = h('div', { class: 'acceso__campo', hidden: true },
    h('label', { class: 'acceso__etiqueta', for: 'acc-repite' }, 'Repite la contraseña'),
    campoRepite, errRepite);

  const ayuda = h('ul', { class: 'acceso__ayuda', hidden: true, id: 'acc-ayuda' }, AYUDA_REGISTRO.map((t) => h('li', {}, t)));

  /* ---------- Mensajes, botón y cambio de modo ---------- */
  const zonaAviso = h('div', { class: 'acceso__aviso', id: 'acc-aviso' });
  const boton = h('button', { type: 'submit', class: 'btn btn--primario btn--bloque acceso__enviar', id: 'btn-acceso-enviar' });
  const titulo = h('h1', { class: 'acceso__titulo', id: 'acceso-titulo', tabindex: '-1' });
  const sub = h('p', { class: 'tarjeta__texto', id: 'acceso-sub' });
  const cambioTexto = h('span', {});
  const cambioBoton = h('button', { type: 'button', class: 'enlace-boton', id: 'btn-acceso-cambiar' });

  const pestanaLogin = h('button', { type: 'button', role: 'tab', class: 'pestana', id: 'pest-login', 'aria-controls': 'panel-acceso', onclick: () => cambiarModo('login') }, 'Iniciar sesión');
  const pestanaRegistro = h('button', { type: 'button', role: 'tab', class: 'pestana', id: 'pest-registro', 'aria-controls': 'panel-acceso', onclick: () => cambiarModo('registro') }, 'Crear cuenta');
  const pestanas = h('div', { class: 'pestanas acceso__pestanas', role: 'tablist', 'aria-label': 'Tipo de acceso' }, pestanaLogin, pestanaRegistro);

  const formulario = h('form', { class: 'acceso__form', id: 'form-acceso', novalidate: true, onsubmit: enviar },
    h('div', { class: 'acceso__campo' },
      h('label', { class: 'acceso__etiqueta', for: 'acc-usuario' }, 'Usuario'),
      campoUsuario, errUsuario),
    h('div', { class: 'acceso__campo' },
      h('label', { class: 'acceso__etiqueta', for: 'acc-clave' }, 'Contraseña'),
      h('div', { class: 'campo-clave' }, campoClave, botonOjo),
      errClave),
    filaRepite, ayuda, boton);

  const panel = h('div', { role: 'tabpanel', id: 'panel-acceso' }, zonaAviso, formulario);

  const el = h('section', { class: 'acceso', 'aria-labelledby': 'acceso-titulo' },
    h('div', { class: 'tarjeta acceso__tarjeta' },
      h('div', { class: 'acceso__marca' }, icono('escudo', { tam: 28 }), h('span', {}, 'SyntaxGuard')),
      titulo, sub, pestanas, panel,
      h('p', { class: 'acceso__cambio' }, cambioTexto, ' ', cambioBoton)));

  /* ---------- Mensajes ---------- */
  function mostrarAviso(tipo, texto) {
    // tipo: 'error' | 'aviso' | 'ok'. Los errores usan role=alert; el resto, status.
    if (!texto) { zonaAviso.replaceChildren(); return; }
    const alerta = tipo === 'error';
    zonaAviso.replaceChildren(h('div', { class: `aviso aviso--${tipo}`, role: alerta ? 'alert' : 'status' },
      icono(tipo === 'ok' ? 'check' : 'alerta', { tam: 16 }), h('span', {}, String(texto))));
  }

  function marcarCampo(campo, errorEl, texto) {
    if (texto) {
      errorEl.textContent = String(texto);
      errorEl.hidden = false;
      campo.setAttribute('aria-invalid', 'true');
    } else {
      errorEl.textContent = '';
      errorEl.hidden = true;
      campo.removeAttribute('aria-invalid');
    }
  }

  function limpiarErrores() {
    marcarCampo(campoUsuario, errUsuario, null);
    marcarCampo(campoClave, errClave, null);
    marcarCampo(campoRepite, errRepite, null);
    mostrarAviso('error', null);
  }

  /* ---------- Estado del botón (envío en curso y bloqueo por demasiados intentos) ---------- */
  function restante() { return (bloqueoHasta[modoActual] - Date.now()) / 1000; }

  function pintarBoton() {
    const t = TEXTOS[modoActual];
    const bloqueado = restante() > 0;
    boton.disabled = enCurso || bloqueado;
    formulario.setAttribute('aria-busy', String(enCurso));
    if (enCurso) boton.replaceChildren(h('span', { class: 'spinner spinner--claro', 'aria-hidden': 'true' }), t.enCurso);
    else if (bloqueado) boton.replaceChildren(`Reintentar en ${fmtCuenta(restante())}`);
    else boton.replaceChildren(t.boton);
  }

  function detenerReloj() { if (reloj) { clearInterval(reloj); reloj = null; } }
  function iniciarReloj() {
    if (reloj) return;
    reloj = setInterval(() => {
      if (!el.isConnected) { detenerReloj(); return; }
      pintarBoton();
      if (Math.max(bloqueoHasta.login, bloqueoHasta.registro) <= Date.now()) {
        detenerReloj();
        if (restante() <= 0 && zonaAviso.querySelector('.aviso--error')) mostrarAviso('aviso', 'Ya puedes volver a intentarlo.');
      }
    }, 1000);
  }

  /* ---------- Modo ---------- */
  function pintarModo() {
    const t = TEXTOS[modoActual];
    const esRegistro = modoActual === 'registro';
    titulo.textContent = t.titulo;
    sub.textContent = t.sub;
    cambioTexto.textContent = t.cambio;
    cambioBoton.textContent = t.cambioBoton;
    pestanaLogin.setAttribute('aria-selected', String(!esRegistro));
    pestanaRegistro.setAttribute('aria-selected', String(esRegistro));
    pestanaLogin.tabIndex = esRegistro ? -1 : 0;
    pestanaRegistro.tabIndex = esRegistro ? 0 : -1;
    panel.setAttribute('aria-labelledby', esRegistro ? 'pest-registro' : 'pest-login');
    campoClave.setAttribute('autocomplete', esRegistro ? 'new-password' : 'current-password');
    campoRepite.required = esRegistro;
    filaRepite.hidden = !esRegistro;
    ayuda.hidden = !esRegistro;
    campoUsuario.setAttribute('aria-describedby', esRegistro ? 'acc-ayuda acc-err-usuario' : 'acc-err-usuario');
    pintarBoton();
  }

  function cambiarModo(nuevo) {
    if (enCurso || nuevo === modoActual) return;
    modoActual = nuevo;
    // Se conserva el usuario escrito; las contraseñas y los errores no pasan de una pestaña a la otra.
    campoClave.value = '';
    campoRepite.value = '';
    visible = false;
    pintarOjo();
    limpiarErrores();
    pintarModo();
    if (restante() > 0) iniciarReloj();
    campoUsuario.focus();
  }
  cambioBoton.addEventListener('click', () => cambiarModo(modoActual === 'login' ? 'registro' : 'login'));
  pestanas.addEventListener('keydown', (ev) => {
    const destino = { ArrowLeft: 'login', ArrowUp: 'login', Home: 'login', ArrowRight: 'registro', ArrowDown: 'registro', End: 'registro' }[ev.key];
    if (!destino) return;
    ev.preventDefault();
    cambiarModo(destino);
    (destino === 'login' ? pestanaLogin : pestanaRegistro).focus();
  });

  /* ---------- Envío ---------- */
  function validarLocal(usuario, clave, repite) {
    const campos = {};
    if (!usuario.trim()) campos.usuario = 'Escribe tu usuario.';
    if (!clave) campos.contrasena = 'Escribe tu contraseña.';
    if (modoActual === 'registro' && clave && repite !== clave) campos.repite = 'Las contraseñas no coinciden.';
    return campos;
  }

  function mostrarCampos(campos, resumen) {
    const c = campos || {};
    marcarCampo(campoUsuario, errUsuario, typeof c.usuario === 'string' ? c.usuario : null);
    marcarCampo(campoClave, errClave, typeof c.contrasena === 'string' ? c.contrasena : null);
    marcarCampo(campoRepite, errRepite, typeof c.repite === 'string' ? c.repite : null);
    // Claves que la pantalla no conoce (p. ej. «cuerpo»): se muestran en el resumen, nunca se descartan en silencio.
    const otros = Object.entries(c).filter(([k, v]) => !['usuario', 'contrasena', 'repite'].includes(k) && typeof v === 'string').map(([, v]) => v);
    if (resumen || otros.length) mostrarAviso('error', [resumen, ...otros].filter(Boolean).join(' '));
    const primero = [[campoUsuario, errUsuario], [campoClave, errClave], [campoRepite, errRepite]].find(([, e]) => !e.hidden);
    if (primero) primero[0].focus();
  }

  function manejarError(e) {
    const clave = modoActual;
    if (!(e instanceof ErrorApi)) { mostrarAviso('error', 'Ocurrió un error inesperado. Inténtalo de nuevo.'); return; }
    switch (e.codigo) {
      case 'credenciales_invalidas':
        mostrarAviso('error', e.message);
        campoClave.value = '';
        campoClave.focus();
        return;
      case 'usuario_duplicado':
      case 'datos_invalidos':
        mostrarCampos(e.campos, e.message);
        return;
      case 'demasiados_intentos': {
        const seg = Number.isFinite(e.reintentarEn) && e.reintentarEn > 0 ? e.reintentarEn : 60;
        bloqueoHasta[clave] = Date.now() + seg * 1000;
        mostrarAviso('error', e.message);
        iniciarReloj();
        return;
      }
      default:
        // Red, tiempo agotado, 403 de seguridad, 5xx…: el mensaje de api.js ya está en español y sin detalles internos.
        mostrarAviso('error', e.message);
    }
  }

  async function enviar(ev) {
    ev.preventDefault();
    if (enCurso || restante() > 0) return; // evita envíos duplicados por Enter o doble clic
    limpiarErrores();
    const campos = validarLocal(campoUsuario.value, campoClave.value, campoRepite.value);
    if (Object.keys(campos).length) { mostrarCampos(campos, null); return; }

    const esRegistro = modoActual === 'registro';
    enCurso = true;
    pintarBoton();
    try {
      if (esRegistro) await registrar(campoUsuario.value, campoClave.value);
      else await iniciarSesion(campoUsuario.value, campoClave.value);
      // Con éxito las contraseñas no se conservan en la pantalla.
      campoClave.value = '';
      campoRepite.value = '';
      const nombre = obtener().sesion.usuario?.usuario;
      toast(esRegistro ? `Cuenta creada. Ya iniciaste sesión${nombre ? ` como ${nombre}` : ''}.` : 'Sesión iniciada.', 'ok');
    } catch (e) {
      // Con error se conserva lo escrito para corregirlo (salvo credenciales incorrectas: manejarError vacía la contraseña).
      if (el.isConnected) manejarError(e);
    } finally {
      visible = false; // la contraseña vuelve a quedar oculta después de cada envío
      pintarOjo();
      enCurso = false;
      if (el.isConnected) pintarBoton();
    }
  }

  /* ---------- Arranque ---------- */
  if (aviso && aviso.texto) mostrarAviso(aviso.tipo === 'ok' ? 'ok' : 'aviso', aviso.texto);
  pintarOjo();
  pintarModo();

  return {
    el,
    destruir: () => { detenerReloj(); campoClave.value = ''; campoRepite.value = ''; },
    // Foco del título (para lectores de pantalla) o del primer campo.
    enfocar: (aCampo = false) => (aCampo ? campoUsuario : titulo).focus({ preventScroll: true }),
  };
}
