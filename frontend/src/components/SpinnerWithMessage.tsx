import Spinner from "./Spinner";

export default function SpinnerWithMessage() {
  return (
    <div className="flex flex-col items-center py-6 space-y-3">
      <Spinner />
      <p className="text-gray-600 text-sm text-center">
        Please wait — the model is thinking hard and returning a response...
      </p>
      <p className="text-gray-500 text-xs italic text-center">
        This one’s running right on Josh’s PC, so it’s not exactly Formula&nbsp;1 speed 🚗💨
      </p>
    </div>
  );
}
