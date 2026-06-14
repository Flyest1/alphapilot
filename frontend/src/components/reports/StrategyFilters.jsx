import { STRATEGY_FILTER_LABELS } from "../../constants/strings.js";
import { STRATEGY_FILTERS, STRATEGY_SORTS } from "../../utils/strategyFilters.js";

export default function StrategyFilters({
  strategyGroup,
  strategyFilter,
  strategySort,
  onGroupChange,
  onFilterChange,
  onSortChange,
}) {
  return (
    <>
      <div className="filter-row">
        <button
          className={strategyGroup === "owned" ? "active" : ""}
          type="button"
          onClick={() => onGroupChange("owned")}
        >
          보유 자산
        </button>
        <button
          className={strategyGroup === "candidates" ? "active" : ""}
          type="button"
          onClick={() => onGroupChange("candidates")}
        >
          추가 후보
        </button>
      </div>
      <div className="filter-row">
        {STRATEGY_FILTERS.map((filter) => (
          <button
            className={strategyFilter === filter ? "active" : ""}
            key={filter}
            type="button"
            onClick={() => onFilterChange(filter)}
          >
            {STRATEGY_FILTER_LABELS[filter]}
          </button>
        ))}
      </div>
      <div className="filter-row">
        {STRATEGY_SORTS.map((sort) => (
          <button
            className={strategySort === sort.key ? "active" : ""}
            key={sort.key}
            type="button"
            onClick={() => onSortChange(sort.key)}
          >
            {sort.label}
          </button>
        ))}
      </div>
    </>
  );
}
