// Open external links in a new tab.
window.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("a.external").forEach(function (link) {
        link.setAttribute("target", "_blank");
    });
});
