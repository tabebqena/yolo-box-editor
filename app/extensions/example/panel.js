// Example sandboxed UI panel.
//
// This runs inside an opaque-origin iframe with no network. It can only reach
// the app through the async `YBE` object, and the host decides what that
// exposes. Here we just list the dataset's tags and mark the ones on the
// current image; every string is written with textContent (never innerHTML),
// since tag names are user data.
(async function () {
  const body = document.body;

  function el(tag, text) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    return node;
  }

  async function refresh() {
    const [available, current] = await Promise.all([
      YBE.state.getAvailableTags(),
      YBE.state.getTags(),
    ]);
    body.textContent = '';
    body.appendChild(el('h3', 'Tags'));
    if (!available.length) {
      body.appendChild(el('p', 'No tags.yaml — add a tag from the tag bar.'));
      return;
    }
    const list = el('ul');
    available.forEach(function (tag) {
      const item = el('li', tag + (current.indexOf(tag) >= 0 ? '  \u2713' : ''));
      list.appendChild(item);
    });
    body.appendChild(list);
  }

  YBE.on('image_loaded', refresh);
  YBE.on('tags_changed', refresh);
  YBE.on('images_list_loaded', refresh);
  refresh();
}());
