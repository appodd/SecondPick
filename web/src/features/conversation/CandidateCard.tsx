import type { CandidateSummary } from "../../api/types";

export interface CandidateCardProps {
  candidate: CandidateSummary;
  onSelectListing: (listingId: number) => void;
  selected?: boolean;
}

export function CandidateCard({
  candidate,
  onSelectListing,
  selected,
}: CandidateCardProps) {
  const details = [
    candidate.price_text,
    candidate.location,
    candidate.seller_name,
  ].filter(Boolean);

  return (
    <article
      className={
        selected ? "candidate-card candidate-card--selected" : "candidate-card"
      }
    >
      <button
        type="button"
        className="candidate-card__button"
        onClick={() => onSelectListing(candidate.listing_id)}
      >
        <span className="candidate-card__title">{candidate.title}</span>
        {details.length > 0 ? (
          <span className="candidate-card__meta">{details.join(" · ")}</span>
        ) : null}
        {candidate.search_description ? (
          <span className="candidate-card__description">
            {candidate.search_description}
          </span>
        ) : null}
      </button>
    </article>
  );
}
