// Example sandboxed UI panel.
//
// This runs inside an opaque-origin iframe with no network. It can only reach
// the app through the async `YBE` object, and the host decides what that
// exposes. Here we just show the current image and its box count.
(async function () {
  var body = document.body;

  function el(tag, text) {
    var node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    return node;
  }

  async function refresh() {
    var img = await YBE.state.getImage();
    var boxes = img ? await YBE.state.getBoxes() : [];
    body.textContent = '';
    body.appendChild(el('h3', 'Example panel'));
    if (!img) {
      body.appendChild(el('p', 'No image loaded.'));
      return;
    }
    body.appendChild(el('p', img.split + '/' + img.name + ' — ' + boxes.length + ' box(es)'));
  }

  YBE.on('image_loaded', refresh);
  YBE.on('boxes_changed', refresh);
  YBE.on('images_list_loaded', refresh);
  refresh();
}());
