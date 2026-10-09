// v4 panel fixture: reads state only.
(async function () {
  var img = await YBE.state.getImage();
  document.body.textContent = img ? img.name : 'no image';
}());
