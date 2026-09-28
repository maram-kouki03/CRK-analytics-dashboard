"""Événements acceptés par /ingest.

Le boîtier n'envoie que trois types, dans des lots qui contiennent l'un, l'autre
ou les trois :

    ENTRY        store_id, ts, track_id                une personne entre
    INTERACTION  store_id, ts, track_id, duration_s    un vendeur l'aborde
    HEARTBEAT    store_id, ts, seller_count            signe de vie du boîtier

Principe : l'API accepte TOUT ce que le boîtier a le droit d'envoyer, y compris
des champs que la base ne conserve pas. Refuser un événement ferait échouer le
lot ENTIER — jusqu'à 1000 événements perdus — alors qu'ignorer un champ en trop
ne coûte rien.

Ce qui est réellement écrit en base (voir db.STORED_EVENT_TYPES) :
    ENTRY        -> store_id, ts, track_id
    INTERACTION  -> store_id, ts, track_id

Ce qui est accepté puis ignoré :
    HEARTBEAT    aucun indicateur ne s'en sert — le KPI « vendeurs actifs » a
                 été retiré du dashboard — mais le boîtier l'envoie, donc on
                 l'accepte pour ne jamais lui renvoyer d'erreur.
    duration_s   le boîtier applique lui-même sa règle de durée minimale avant
                 d'émettre une INTERACTION : le backend compte ce qui arrive, il
                 ne rejuge pas. Plus aucun indicateur de durée n'est affiché.

Les anciens types PEC / PEC_START / PEC_END ont été retirés : le boîtier ne les
envoie plus. Les lignes correspondantes restent en base mais ne sont plus
comptées (voir le README).

ENTRY et INTERACTION sont tous deux identifiés par leur track_id — la règle de
comptage est dans analytics._unique_tracks.
"""

from typing import Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, Field


class EntryEvent(BaseModel):
    store_id: str
    event_type: Literal["ENTRY"]
    ts: float
    # Numéro attribué par le tracker à la personne suivie. Optionnel : une entrée
    # sans track_id est comptée quand même, elle ne peut juste pas être
    # dédoublonnée d'une re-détection.
    track_id: Optional[int] = None


class InteractionEvent(BaseModel):
    """UNE ligne par prise en charge, déjà filtrée à bord du boîtier.

    Ni paire START/END, ni identifiant métier : l'interaction est identifiée par
    le track_id de la personne prise en charge, exactement comme une ENTRY.

    track_id est requis — sans lui l'interaction n'a pas d'identité du tout.
    duration_s reste optionnel : un boîtier qui cesserait de l'envoyer ne doit
    pas faire rejeter un lot entier.
    """

    store_id: str
    event_type: Literal["INTERACTION"]
    ts: float
    track_id: int
    duration_s: Optional[float] = None  # accepté, non stocké


class HeartbeatEvent(BaseModel):
    # Accepté, non stocké — voir le docstring du module.
    store_id: str
    event_type: Literal["HEARTBEAT"]
    ts: float
    seller_count: int


IngestEvent = Annotated[
    Union[EntryEvent, InteractionEvent, HeartbeatEvent],
    Field(discriminator="event_type"),
]


class BatchRequest(BaseModel):
    events: List[IngestEvent] = Field(..., max_length=1000)
