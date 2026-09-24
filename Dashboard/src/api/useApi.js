import { useCallback, useEffect, useState } from "react";

import { fetchStores } from "./client";

/**
 * Charge une ressource du backend et suit son état.
 *
 * `fetcher` est recréé à chaque render : ce sont les `deps` qui décident quand
 * relancer la requête, exactement comme pour useMemo.
 *
 *   const { data, error, loading } = useApi(
 *     () => fetchRange(store, start, end), [store, start, end]);
 */
export function useApi(fetcher, deps) {
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(fetcher, deps);
  const [state, setState] = useState({ data: null, error: null, loading: true });

  useEffect(() => {
    let current = true;
    // On garde `data` pendant le rechargement : changer de magasin ne fait pas
    // clignoter la page en vidant les graphes avant d'avoir la réponse.
    setState((prev) => ({ ...prev, loading: true, error: null }));

    run().then(
      (data) => current && setState({ data, error: null, loading: false }),
      (error) => current && setState({ data: null, error, loading: false })
    );

    return () => {
      current = false;
    };
  }, [run]);

  return state;
}

/** Liste des magasins, partagée par la Vue d'ensemble et les Rapports. */
export function useStores() {
  const { data, error, loading } = useApi(() => fetchStores(), []);
  const liste = data ?? [];

  // Magasin d'ouverture : le plus récemment actif. Prendre le premier de la liste
  // ferait tomber sur une boutique dont le boîtier s'est tu il y a des semaines,
  // et le dashboard s'ouvrirait vide sans que ce soit un bug.
  const actifs = liste.filter((s) => s.dernierEvenementTs != null);
  const defaut = actifs.length
    ? actifs.reduce((a, b) => (b.dernierEvenementTs > a.dernierEvenementTs ? b : a)).nom
    : liste[0]?.nom ?? null;

  return {
    stores: liste.map((s) => s.nom),
    sansDonnees: new Set(liste.filter((s) => !s.aDonnees).map((s) => s.nom)),
    defaut,
    error,
    loading,
  };
}
