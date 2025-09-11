import { Paperclip, Square, SendHorizonal } from "lucide-react";

type Props = {
  disabledUpload: boolean;
  onPickFile: () => void;
  showStop: boolean;
  onStop: () => void;
  showSend: boolean;
  onSend: () => void;
};

export default function ComposerActions({
  disabledUpload,
  onPickFile,
  showStop,
  onStop,
  showSend,
  onSend,
}: Props) {
  return (
    <div className="flex items-end gap-2">
      <button
        className={`p-2 rounded-lg border hover:bg-gray-50 ${disabledUpload ? "opacity-60 cursor-not-allowed" : ""}`}
        onClick={onPickFile}
        title="Upload to this chat"
        aria-label="Upload to this chat"
        disabled={disabledUpload}
      >
        <Paperclip size={18} />
      </button>

      {showStop ? (
        <button
          className="p-2 rounded-lg border hover:bg-gray-50"
          onClick={onStop}
          title="Stop generating"
          aria-label="Stop generating"
        >
          <Square size={18} />
        </button>
      ) : showSend ? (
        <button
          className="p-2 rounded-lg bg-black text-white hover:bg-black/90 active:translate-y-px"
          onClick={onSend}
          title="Send"
          aria-label="Send"
        >
          <SendHorizonal size={18} />
        </button>
      ) : null}
    </div>
  );
}
