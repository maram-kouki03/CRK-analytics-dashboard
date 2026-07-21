// ============================================================
// Registre des plans de boutique (photo + zones caméra).
// Une seule boutique a sa photo pour l'instant : MANAR CITY.
// Pour ajouter une boutique : ajouter une entrée ici, rien d'autre
// (le composant ShopMap et le dashboard lisent ce registre par nom de magasin).
//
// zones[].points : polygone en % de l'image (x, y ∈ [0, 100]),
// dans le sens de lecture (facile à ajuster visuellement).
// ============================================================

import manarCityImg from "../assets/boutique-manar-city.png";

const shopMaps = {
  "MANAR CITY": {
    image: manarCityImg,
    zones: [
      {
        id: 1,
        nom: "Mur gauche",
        points: [
          // AJUSTER LES COORDONNÉES
          { x: 10, y: 8 },
          { x: 45, y: 8 },
          { x: 45, y: 55 },
          { x: 10, y: 55 },
        ],
      },
      {
        id: 2,
        nom: "Îlots centraux & mur droit",
        points: [
          // AJUSTER LES COORDONNÉES
          { x: 45, y: 8 },
          { x: 85, y: 8 },
          { x: 85, y: 60 },
          { x: 45, y: 60 },
        ],
      },
      {
        id: 3,
        nom: "Îlot accessoires",
        points: [
          // AJUSTER LES COORDONNÉES
          { x: 40, y: 62 },
          { x: 75, y: 62 },
          { x: 75, y: 95 },
          { x: 40, y: 95 },
        ],
      },
    ],
  },
};

export default shopMaps;
