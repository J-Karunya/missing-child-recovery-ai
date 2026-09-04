"""DeepSORT tracker construction kept separate from matching logic."""


def create_tracker():
    try:
        from deep_sort_realtime.deepsort_tracker import DeepSort
    except ImportError as exc:
        raise RuntimeError("deep-sort-realtime is not installed. Install requirements.txt first.") from exc
    return DeepSort(max_age=30, n_init=3, max_cosine_distance=0.4)
