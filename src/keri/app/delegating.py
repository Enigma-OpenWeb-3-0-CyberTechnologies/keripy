# -*- encoding: utf-8 -*-
"""
KERI
keri.app.delegating module

module for enveloping and forwarding KERI message
"""

from hio import help
from hio.base import doing
from hio.help import decking

from . import agenting, forwarding
from .habbing import GroupHab
from .. import kering
from ..core import coring
from ..db import dbing
from ..peer import exchanging

logger = help.ogler.getLogger()


class Boatswain(doing.DoDoer):
    """
    Sends messages to Delegator of an identifier and wait for the anchoring event to
    be processed to ensure the inception or rotation event has been approved by the delegator.

    Removes all Doers and exits as Done once the event has been anchored.

    """

    def __init__(self, hby, **kwa):
        """
        For the current event, gather the current set of witnesses, send the event,
        gather all receipts and send them to all other witnesses

        Parameters:
            hab (Hab): Habitat of the identifier to populate witnesses
            msg (bytes): is the message to send to all witnesses.
                 Defaults to sending the latest KEL event if msg is None
            scheme (str): Scheme to favor if available

        """
        self.hby = hby
        self.postman = forwarding.Poster(hby=hby)
        self.witq = agenting.WitnessInquisitor(hby=hby)
        self.witDoer = agenting.Receiptor(hby=self.hby)

        super(Boatswain, self).__init__(doers=[self.witq, self.witDoer, self.postman, doing.doify(self.escrowDo)],
                                        **kwa)

    def delegation(self, pre, sn=None, proxy=None):
        if pre not in self.hby.habs:
            raise kering.ValidationError(f"{pre} is not a valid local AID for delegation")

        # load the hab of the delegated identifier to anchor
        hab = self.hby.habs[pre]
        delpre = hab.kever.delegator  # get the delegator identifier
        if delpre not in hab.kevers:
            raise kering.ValidationError(f"delegator {delpre} not found, unable to process delegation")

        dkever = hab.kevers[delpre]  # and the delegator's kever
        sn = sn if sn is not None else hab.kever.sner.num

        # load the event and signatures
        evt = hab.makeOwnEvent(sn=sn)
        srdr = coring.Serder(raw=evt)
        del evt[:srdr.size]

        smids = []
        if isinstance(hab, GroupHab):
            phab = hab.mhab
            smids = hab.smids
        elif hab.kever.sn > 0:
            phab = hab
        elif proxy is not None:
            phab = proxy
        else:
            raise kering.ValidationError("no proxy to send messages for delegation")

        # Send exn message for notification purposes
        exn, atc = delegateRequestExn(phab, delpre=delpre, ked=srdr.ked, aids=smids)

        self.postman.send(hab=phab, dest=hab.kever.delegator, topic="delegate", serder=exn, attachment=atc)
        self.postman.send(hab=phab, dest=delpre, topic="delegate", serder=srdr, attachment=evt)

        anchor = dict(i=srdr.pre, s=srdr.sn, d=srdr.said)
        self.witq.query(hab=phab, pre=dkever.prefixer.qb64, anchor=anchor)

        self.hby.db.dune.pin(keys=(srdr.pre, srdr.said), val=srdr)

    def complete(self, prefixer, seqner, saider=None):
        """ Check for completed delegation protocol for the specific event

        Parameters:
            prefixer (Prefixer): qb64 identifier prefix of event to check
            seqner (Seqner): sequence number of event to check
            saider (Saider): optional digest of event to verify

        Returns:

        """
        csaider = self.hby.db.cdel.get(keys=(prefixer.qb64, seqner.qb64))
        if not csaider:
            return False
        else:
            if saider and (csaider.qb64 != saider.qb64):
                raise kering.ValidationError(f"invalid delegation protocol escrowed event {csaider.qb64}-{saider.qb64}")

        return True

    def escrowDo(self, tymth, tock=1.0):
        """ Process escrows of group multisig identifiers waiting to be compeleted.

        Steps involve:
           1. Sending local event with sig to other participants
           2. Waiting for signature threshold to be met.
           3. If elected and delegated identifier, send complete event to delegator
           4. If delegated, wait for delegator's anchor
           5. If elected, send event to witnesses and collect receipts.
           6. Otherwise, wait for fully receipted event

        Parameters:
            tymth (function): injected function wrapper closure returned by .tymen() of
                Tymist instance. Calling tymth() returns associated Tymist .tyme.
            tock (float): injected initial tock value.  Default to 1.0 to slow down processing

        """
        # enter context
        self.wind(tymth)
        self.tock = tock
        _ = (yield self.tock)

        while True:
            self.processEscrows()
            yield 0.5

    def processEscrows(self):
        self.processUnanchoredEscrow()
        self.processPartialWitnessEscrow()

    def processUnanchoredEscrow(self):
        """
        Process escrow of partially signed multisig group KEL events.  Message
        processing will send this local controllers signature to all other participants
        then this escrow waits for signatures from all other participants

        """
        for (pre, said), serder in self.hby.db.dune.getItemIter():  # group partial witness escrow
            kever = self.hby.kevers[pre]
            dkever = self.hby.kevers[kever.delegator]

            anchor = dict(i=serder.pre, s=serder.sn, d=serder.said)
            if dserder := self.hby.db.findAnchoringEvent(dkever.prefixer.qb64, anchor=anchor):
                seqner = coring.Seqner(sn=dserder.sn)
                couple = seqner.qb64b + dserder.saidb
                dgkey = dbing.dgKey(kever.prefixer.qb64b, kever.serder.saidb)
                self.hby.db.setAes(dgkey, couple)  # authorizer event seal (delegator/issuer)
                self.witDoer.msgs.append(dict(pre=pre, sn=serder.sn))

                # Move to escrow waiting for witness receipts
                print(f"Waiting for fully signed witness receipts for {serder.sn}")
                self.hby.db.dpwe.pin(keys=(pre, said), val=serder)
                self.hby.db.dune.rem(keys=(pre, said))

    def processPartialWitnessEscrow(self):
        """
        Process escrow of delegated events that do not have a full compliment of receipts
        from witnesses yet.  When receipting is complete, remove from escrow and cue up a message
        that the event is complete.

        """
        for (pre, said), serder in self.hby.db.dpwe.getItemIter():  # group partial witness escrow
            kever = self.hby.kevers[pre]
            dgkey = dbing.dgKey(pre, serder.said)
            seqner = coring.Seqner(sn=serder.sn)

            # Load all the witness receipts we have so far
            wigs = self.hby.db.getWigs(dgkey)
            if len(wigs) == len(kever.wits):  # We have all of them, this event is finished
                if len(kever.wits) > 0:
                    witnessed = False
                    for cue in self.witDoer.cues:
                        if cue["pre"] == serder.pre and cue["sn"] == seqner.sn:
                            witnessed = True
                    if not witnessed:
                        continue
                print(f"Witness receipts complete, {pre} confirmed.")
                self.hby.db.dpwe.rem(keys=(pre, said))
                self.hby.db.cdel.put(keys=(pre, seqner.qb64), val=serder.saider)


def loadHandlers(hby, exc, notifier):
    """ Load handlers for the peer-to-peer delegation protocols

    Parameters:
        hby (Habery): Database and keystore for environment
        exc (Exchanger): Peer-to-peer message router
        notifier (Notifier): Outbound notifications

    """
    delreq = DelegateRequestHandler(hby=hby, notifier=notifier)
    exc.addHandler(delreq)


class DelegateRequestHandler(doing.DoDoer):
    """
    Handler for multisig group inception notification EXN messages

    """
    resource = "/delegate/request"

    def __init__(self, hby, notifier, **kwa):
        """

        Parameters:
            mbx (Mailboxer) of format str names accepted for offers
            controller (str) qb64 identity prefix of controller
            cues (decking.Deck) of outbound cue messages from handler

        """
        self.hby = hby
        self.notifier = notifier
        self.msgs = decking.Deck()
        self.cues = decking.Deck()

        super(DelegateRequestHandler, self).__init__(**kwa)

    def do(self, tymth, tock=0.0, **opts):
        """

        Handle incoming messages by parsing and verifying the credential and storing it in the wallet

        Parameters:
            payload is dict representing the body of a multisig/incept message
            pre is qb64 identifier prefix of sender
            sigers is list of Sigers representing the sigs on the /credential/issue message
            verfers is list of Verfers of the keys used to sign the message

        """
        self.wind(tymth)
        self.tock = tock
        yield self.tock

        while True:
            while self.msgs:
                msg = self.msgs.popleft()
                if "pre" not in msg:
                    logger.error(f"invalid delegate request message, missing pre.  evt=: {msg}")
                    continue

                prefixer = msg["pre"]
                if "payload" not in msg:
                    logger.error(f"invalid delegate request message, missing payload.  evt=: {msg}")
                    continue

                pay = msg["payload"]
                if "ked" not in pay or "delpre" not in pay:
                    logger.error(f"invalid delegate request payload, ked and delpre are required.  payload=: {pay}")
                    continue

                src = prefixer.qb64
                delpre = pay["delpre"]
                if delpre not in self.hby.habs:
                    logger.error(f"invalid delegate request message, no local delpre for evt=: {pay}")
                    continue

                data = dict(
                    src=src,
                    r='/delegate/request',
                    delpre=delpre,
                    ked=pay["ked"]
                )
                if "aids" in pay:
                    data["aids"] = pay["aids"]

                self.notifier.add(attrs=data)
                # if I am multisig, send oobi information of participants in (delegateeeeeeee) mutlisig group to his
                # multisig group

                yield
            yield


def delegateRequestExn(hab, delpre, ked, aids=None):
    data = dict(
        delpre=delpre,
        ked=ked
    )

    if aids is not None:
        data["aids"] = aids

    # Create `exn` peer to peer message to notify other participants UI
    exn = exchanging.exchange(route=DelegateRequestHandler.resource, modifiers=dict(),
                              payload=data)
    ims = hab.endorse(serder=exn, last=True, pipelined=False)
    del ims[:exn.size]

    return exn, ims
