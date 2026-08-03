# Universal Campaign Template — Field Mapping by Campaign Type

The template (`reach-universal-campaign-template.html`) has one fixed shell (logo, headline,
greeting/body, signature, footer) and two **optional** blocks (details table, CTA button)
that get filled differently — or removed entirely — depending on campaign type.

---

## 1. Health Checkup Reminder (event-style)

| Placeholder | Value |
|---|---|
| CampaignHeadline | Your Annual Health Checkup is Scheduled! |
| DetailLabel1 / DetailValue1 | Date / Sunday, 27 July 2026 |
| DetailLabel2 / DetailValue2 | Time / 9:00 AM – 1:00 PM |
| DetailLabel3 / DetailValue3 | Location / Sciens HQ, Conference Hall |
| ActionLabel / ActionUrl | Confirm My Slot / (registration link) |

**Uses:** details table ✅ | CTA ✅

---

## 2. Job Opportunity Alert (Codegnan-style)

| Placeholder | Value |
|---|---|
| CampaignHeadline | New Job Opportunity! |
| DetailLabel1 / DetailValue1 | Company / Prudent Technologies |
| DetailLabel2 / DetailValue2 | Role / Junior Data & AI Engineer |
| DetailLabel3 / DetailValue3 | Work Mode / On-site |
| ActionLabel / ActionUrl | View Full Details / (job posting link) |

**Uses:** details table ✅ | CTA ✅

---

## 3. Plain Announcement (no structured details, no action)

| Placeholder | Value |
|---|---|
| CampaignHeadline | Office Closed for Festival Holiday |
| MessageBody | Our office will remain closed on Monday, 3 August for the festival holiday. Regular operations resume Tuesday. |

**Uses:** details table ❌ (delete block) | CTA ❌ (delete block)

---

## How to reuse this per campaign in Reach

1. Start from `reach-universal-campaign-template.html`.
2. Decide: does this campaign need a details table? Need a CTA button? Delete the
   corresponding `<tr>...</tr>` block(s) if not (marked clearly with comments in the file).
3. Fill in `{{CampaignHeadline}}`, `{{MessageBody}}`, and whichever `{{DetailLabelN}}` /
   `{{DetailValueN}}` pairs apply — these can hold *any* label, not just event details.
4. Leave the signature block (#6) and footer (#7) untouched — these stay identical across
   every campaign, driven by the Project-level branding config.
