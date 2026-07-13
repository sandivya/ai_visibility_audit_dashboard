type LoadMoreButtonProps = {
  isLoading: boolean;
  onLoad: () => void;
  label: string;
  fullWidth?: boolean;
};

export function LoadMoreButton({
  isLoading,
  onLoad,
  label,
  fullWidth = false,
}: LoadMoreButtonProps) {
  return (
    <button
      type="button"
      className={fullWidth ? "secondary evidence-more" : undefined}
      onClick={onLoad}
      disabled={isLoading}
      aria-busy={isLoading}
    >
      {isLoading ? "Loading more…" : label}
    </button>
  );
}
