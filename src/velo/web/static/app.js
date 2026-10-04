// Progressive enhancement only: the form works without this script.
(function () {
  var form = document.getElementById("pick");
  if (!form) return;
  var rows = Array.prototype.slice.call(form.querySelectorAll(".field"));
  var count = document.getElementById("count");
  var filter = document.getElementById("filter");

  function refresh() {
    var n = 0;
    rows.forEach(function (row) {
      var on = row.querySelector(".sel").checked;
      row.classList.toggle("on", on);
      row.querySelectorAll("select").forEach(function (s) { s.disabled = !on; });
      if (on) n += 1;
    });
    count.textContent = n;
  }

  form.addEventListener("change", function (e) {
    if (e.target.classList.contains("sel")) refresh();
  });

  if (filter) {
    filter.addEventListener("input", function () {
      var q = filter.value.trim().toLowerCase();
      rows.forEach(function (row) {
        row.hidden = q !== "" && row.getAttribute("data-name").indexOf(q) === -1;
      });
    });
  }
  refresh();
})();
