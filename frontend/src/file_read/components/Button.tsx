interface Props {
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}

export default function Button({ onClick, disabled, children }: Props) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`bg-indigo-600 text-white px-4 py-2 rounded hover:bg-indigo-700 ${
        disabled ? "opacity-50 cursor-not-allowed" : ""
      }`}
    >
      {children}
    </button>
  );
}
