/* ---------------------------------------------------------------------------
   Auction Sentinel — lo poco que esta pagina necesita de JavaScript.

   Dos cosas, y las dos son un añadido: si este fichero no llega, la caja de
   busqueda sigue siendo el formulario GET de siempre y los filtros se siguen
   abriendo, porque son `<details>` nativos. Nada de lo que hay aqui es
   necesario para usar la web ni para rastrearla.

   1. El autocompletar de la caja: pide a /suggest mientras se teclea y pinta
      las sugerencias debajo, sin cambiar de pagina.
   2. Cerrar los desplegables de filtros al abrir otro o al pulsar fuera, que
      es lo unico que `<details>` no hace solo.
   --------------------------------------------------------------------------- */

(function () {
  "use strict";

  // -- El autocompletar de la caja -------------------------------------------

  var caja = document.querySelector('.buscar input[role="combobox"]');
  var lista = document.getElementById("sugerencias");

  if (caja && lista) {
    // Con una sola letra salen cientos de objetos y ninguno es el que se
    // busca: la lista estorba mas de lo que ayuda hasta la segunda.
    var MINIMO = 2;
    // Suficiente para no pedir una vez por tecla al escribir de corrido, y
    // poco para que la lista aparezca mientras se sigue mirando la caja.
    var ESPERA = 140;

    var temporizador = null;
    var peticion = null;
    var filas = [];
    var elegido = -1;

    function cerrar() {
      lista.hidden = true;
      lista.innerHTML = "";
      caja.setAttribute("aria-expanded", "false");
      caja.removeAttribute("aria-activedescendant");
      filas = [];
      elegido = -1;
    }

    function marcar(n) {
      var ops = lista.children;
      for (var i = 0; i < ops.length; i++) {
        ops[i].classList.toggle("elegida", i === n);
        ops[i].setAttribute("aria-selected", i === n ? "true" : "false");
      }
      elegido = n;
      if (n >= 0) {
        // Lo que hace que un lector de pantalla lea la sugerencia al bajar con
        // la flecha: el foco no se mueve de la caja, asi que hay que decirle
        // cual esta senalada.
        caja.setAttribute("aria-activedescendant", ops[n].id);
        ops[n].scrollIntoView({ block: "nearest" });
      } else {
        caja.removeAttribute("aria-activedescendant");
      }
    }

    function ir(n) {
      if (filas[n]) window.location.href = "/item/" + filas[n].producto_id;
    }

    function fila(r, i) {
      var li = document.createElement("li");
      li.id = "sug-" + i;
      li.className = "sug" + (r.calidad ? " q-" + r.calidad.toLowerCase() : "");
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", "false");

      if (r.icono) {
        var img = document.createElement("img");
        img.className = "icono";
        img.src = r.icono;
        img.alt = "";
        img.width = 32;
        img.height = 32;
        li.appendChild(img);
      } else {
        // El mismo hueco que en las tablas: sin el, las filas con icono y las
        // sin el no alinean y la lista baila al teclear.
        var hueco = document.createElement("span");
        hueco.className = "icono icono-vacio";
        li.appendChild(hueco);
      }

      var nombre = document.createElement("span");
      nombre.className = "sug-n";
      // `textContent` y no `innerHTML`: el nombre viene de la base de datos y
      // no se pinta como HTML ni aunque algun dia lleve un "<".
      nombre.textContent = r.nombre;
      li.appendChild(nombre);

      var precio = document.createElement("span");
      precio.className = "sug-p";
      precio.textContent = r.desde + "g";
      li.appendChild(precio);

      li.addEventListener("mousedown", function (e) {
        // `mousedown` y no `click`: el `blur` de la caja llega antes que el
        // click y cerraria la lista justo debajo del dedo.
        e.preventDefault();
        ir(i);
      });
      return li;
    }

    function pintar(resultados) {
      if (!resultados.length) {
        cerrar();
        return;
      }
      filas = resultados;
      lista.innerHTML = "";
      resultados.forEach(function (r, i) {
        lista.appendChild(fila(r, i));
      });
      lista.hidden = false;
      caja.setAttribute("aria-expanded", "true");
      marcar(-1);
    }

    function pedir(texto) {
      // Se aborta la anterior: al teclear rapido salen varias en vuelo y no
      // tienen por que volver en orden.
      if (peticion) peticion.abort();
      peticion = new AbortController();
      fetch("/suggest?q=" + encodeURIComponent(texto), { signal: peticion.signal })
        .then(function (r) {
          return r.json();
        })
        .then(function (d) {
          // La respuesta trae la `q` que la pidio: si ya no es lo que hay en
          // la caja, llega tarde y se tira.
          if (d.q.trim() === caja.value.trim()) pintar(d.resultados);
        })
        .catch(function () {
          // Abortada, o la red caida. No se avisa de nada: la caja sigue
          // siendo un formulario y Enter lleva a /search igual.
        });
    }

    caja.addEventListener("input", function () {
      var texto = caja.value.trim();
      clearTimeout(temporizador);
      if (texto.length < MINIMO) {
        cerrar();
        return;
      }
      temporizador = setTimeout(function () {
        pedir(texto);
      }, ESPERA);
    });

    caja.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        cerrar();
        return;
      }
      if (lista.hidden) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        marcar(elegido + 1 >= filas.length ? 0 : elegido + 1);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        marcar(elegido - 1 < 0 ? filas.length - 1 : elegido - 1);
      } else if (e.key === "Enter" && elegido >= 0) {
        // Solo si hay una senalada. Si no la hay, Enter envia el formulario y
        // lleva a /search, que es lo que hacia antes de existir esto.
        e.preventDefault();
        ir(elegido);
      }
    });

    caja.addEventListener("blur", cerrar);
  }

  // -- Los desplegables de filtros -------------------------------------------
  //
  // `<details>` ya se abre y se cierra solo, y por eso los filtros son eso y
  // no un menu montado a mano. Lo que no hace es cerrarse cuando abres otro o
  // cuando pulsas fuera, y tres menus abiertos a la vez encima de la tabla son
  // justo el desorden que el panel venia a quitar.

  var menus = document.querySelectorAll("details.desplegable");

  menus.forEach(function (d) {
    d.addEventListener("toggle", function () {
      if (!d.open) return;
      menus.forEach(function (otro) {
        if (otro !== d) otro.open = false;
      });
    });
  });

  document.addEventListener("click", function (e) {
    menus.forEach(function (d) {
      if (d.open && !d.contains(e.target)) d.open = false;
    });
  });

  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    menus.forEach(function (d) {
      d.open = false;
    });
  });
})();
