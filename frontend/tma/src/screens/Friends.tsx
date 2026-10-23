import { useReferral } from "../api/hooks";
import type { RewardEntry } from "../api/types";
import { useTranslation } from "../i18n/useTranslation";
import { formatBytes } from "../lib/format";
import { openInTelegram } from "../telegram/links";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { Cell } from "../ui/Cell";
import { CopyButton } from "../ui/CopyButton";
import { ErrorState } from "../ui/ErrorState";
import { Mono } from "../ui/Mono";
import { Note } from "../ui/Note";
import { ProgressBar } from "../ui/ProgressBar";
import { SectionLabel } from "../ui/SectionLabel";
import { Skeleton } from "../ui/Skeleton";

function FriendsSkeleton() {
  return (
    <div className="space-y-3 pt-3.5">
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-40 w-full" />
    </div>
  );
}

export function Friends() {
  const { t, tPlural, lang } = useTranslation();
  const referral = useReferral();

  if (referral.isPending) return <FriendsSkeleton />;
  if (referral.error) {
    return <ErrorState error={referral.error} onRetry={() => void referral.refetch()} />;
  }
  const r = referral.data;

  /** «+30 дней», «+1 устройство», «+100 ГБ» — награда без значков. */
  const reward = (x: Pick<RewardEntry, "days" | "devices" | "traffic_bytes">) =>
    [
      x.days > 0 && `+${tPlural("unit.day", x.days)}`,
      x.devices > 0 && `+${tPlural("unit.device", x.devices)}`,
      x.traffic_bytes > 0 && `+${formatBytes(x.traffic_bytes, lang)}`,
    ]
      .filter(Boolean)
      .join(" · ");

  const shareUrl = r.link
    ? `https://t.me/share/url?url=${encodeURIComponent(r.link)}&text=${encodeURIComponent(
        t("friends.shareText"),
      )}`
    : null;

  const goal = r.next_tier_friends;
  const historyLine = (h: RewardEntry): string => {
    if (h.kind === "tier") {
      return t("friends.rewardTier", { n: h.tier ?? 0, reward: reward(h) });
    }
    if (h.status === "capped") return t("friends.rewardCapped");
    if (h.status === "pending") return t("friends.rewardPending", { days: h.days });
    return t("friends.rewardBase", { days: h.days });
  };

  return (
    <div className="pt-3.5">
      <Card>
        <Cell
          title={t("friends.code")}
          value={
            <span className="flex items-center gap-2">
              <Mono>{r.code}</Mono>
              <CopyButton value={r.link ?? r.code} />
            </span>
          }
        />
        <Cell title={t("friends.invited", { n: r.invited })} />
      </Card>

      <div className="mt-3">
        {shareUrl ? (
          <Button onClick={() => openInTelegram(shareUrl)}>{t("friends.share")}</Button>
        ) : (
          <Note>{t("friends.noLink", { code: r.code })}</Note>
        )}
        <Note className="mt-2 px-1">{t("friends.hint")}</Note>
      </div>

      <SectionLabel>{t("friends.tiers")}</SectionLabel>
      <Card>
        <div className="px-4 py-3.5">
          {goal === null ? (
            <div className="text-[15px] font-semibold">{t("friends.allDone")}</div>
          ) : (
            <>
              <div className="text-[15px] font-semibold">
                {t("friends.progress", { n: r.paying_friends, goal })}
              </div>
              <ProgressBar percent={(r.paying_friends / goal) * 100} />
            </>
          )}
        </div>
        {r.tiers.map((tier) => (
          <Cell
            key={tier.friends}
            title={tPlural("unit.friend", tier.friends)}
            subtitle={[reward(tier), tier.badge && t(`friends.badge.${tier.badge}`)]
              .filter(Boolean)
              .join(" · ")}
            value={tier.reached ? "✓" : undefined}
          />
        ))}
      </Card>

      <section aria-label={t("friends.history")}>
        <SectionLabel>{t("friends.history")}</SectionLabel>
        <Card>
          {r.history.length === 0 ? (
            <div className="px-4 py-3.5">
              <Note>{t("friends.empty")}</Note>
            </div>
          ) : (
            r.history.map((h, i) => (
              <Cell key={`${h.created_at}-${i}`} title={historyLine(h)} />
            ))
          )}
        </Card>
      </section>
    </div>
  );
}
