"""The one-shot forced re-download exemption from the WebUI channel."""

from bilibili_api import aid2bvid, bvid2aid

class RedownloadMixin:

    def request_redownload(self, asset_id):
        """Queue one asset for forced re-download from the WebUI channel.

        Both the BV and av spellings are registered so the exemption applies
        regardless of which key the current source listing happens to use.
        Returns the normalized set of keys to match against.
        """
        keys = set()
        text = str(asset_id or "").strip()
        if not text:
            return keys
        keys.add(text)
        try:
            if text.lower().startswith("av"):
                aid = int(text[2:])
                keys.add(aid2bvid(aid))
            elif text.upper().startswith("BV"):
                keys.add(f"av{bvid2aid(text)}")
        except (TypeError, ValueError, IndexError, KeyError):
            # An unconvertible key still matches itself; it simply will not
            # gain the alternate spelling. bvid2aid raises IndexError on
            # malformed input, so it must be caught here too.
            pass
        self._forced_redownloads.update(keys)
        return keys

    def _consume_forced_redownload(self, db_key):
        """Return True once for a queued key, so a re-download happens once."""
        if not db_key or db_key not in self._forced_redownloads:
            return False
        self._forced_redownloads.discard(db_key)
        return True

    def _should_skip_archived_video(self, db_key, local_record):
        """Return True when a complete archived record may be skipped.

        A WebUI redownload command flips the decision for exactly one pass,
        and the key is consumed here so the next cycle skips it again.
        """
        if self._consume_forced_redownload(db_key):
            print("[*] 已收到重下载指令，将强制重新抓取该资产。")
            return False
        return self._video_record_is_complete(local_record)
