const columns = [
  document.querySelector("#gallery-a"),
  document.querySelector("#gallery-b"),
  document.querySelector("#gallery-c"),
];

const posterTitle = (name) =>
  name
    .replace(/\.(png|jpe?g|webp)$/i, "")
    .replace(/_\d{8}_\d{6}$/i, "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());

const buildPosterCard = (poster) => {
  const card = document.createElement("a");
  card.className = "home-poster";
  card.href = "/studio";
  card.innerHTML = `
    <img src="${poster.url}" alt="${posterTitle(poster.name)}" loading="lazy">
    <span>${posterTitle(poster.name)}</span>
  `;
  return card;
};

const fillColumn = (column, posters) => {
  const loop = [...posters, ...posters];
  column.replaceChildren(...loop.map(buildPosterCard));
};

const loadPosters = async () => {
  const response = await fetch("/api/posters");
  const payload = await response.json();
  const posters = payload.posters || [];

  if (!posters.length) {
    document.querySelector(".home-gallery").innerHTML = `
      <div class="home-empty">
        <strong>Nessun poster ancora generato</strong>
        <span>Apri lo studio e crea il primo.</span>
      </div>
    `;
    return;
  }

  columns.forEach((column, index) => {
    const slice = posters.filter((_, posterIndex) => posterIndex % columns.length === index);
    fillColumn(column, slice.length ? slice : posters);
  });
};

loadPosters().catch(() => {
  document.querySelector(".home-gallery").innerHTML = `
    <div class="home-empty">
      <strong>Galleria non disponibile</strong>
      <span>Puoi comunque aprire lo studio.</span>
    </div>
  `;
});
