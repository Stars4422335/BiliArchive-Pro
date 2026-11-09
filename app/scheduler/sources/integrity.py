"""Sampled integrity verification of archived media."""

import asyncio


class IntegrityMixin:

    async def verify_integrity(self, verifier, batch_size=20):
        """按批抽样校验已完成资产的媒体文件完整性（只报告，不删除）。"""
        if not verifier.enabled:
            return
        candidates = self.db.candidates_for_verify(limit=batch_size)
        if not candidates:
            print("[*] 完整性巡检：暂无待校验资产。")
            return

        print(
            f"\n[>>>] 开始完整性巡检（模式 {verifier.mode}，本批 {len(candidates)} 个资产）"
        )
        corrupt_count = 0
        for asset in candidates:
            ok, reason, checked = verifier.verify_asset(asset)
            if ok:
                self.db.update_integrity(asset["bvid"], self.db.INTEGRITY_OK)
                print(f"[+] 完整性通过: {asset['bvid']}（{checked} 个媒体文件）")
            else:
                self.db.update_integrity(asset["bvid"], self.db.INTEGRITY_CORRUPT)
                corrupt_count += 1
                print(
                    f"[-] 完整性异常: {asset['bvid']}: {reason}"
                    "（已标记，不会自动删除；若源端仍在可考虑重新下载）"
                )
            # 文件 IO 密集，给磁盘喘息
            await asyncio.sleep(0.2)

        print(
            f"[+] 本批巡检完成：通过 {len(candidates) - corrupt_count}，"
            f"异常 {corrupt_count}。"
        )
