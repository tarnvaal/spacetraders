# The queue will be used to schedule events for the game.
# We will use a min-heap priority queue to store the events.

from heapq import heappop, heappush
from typing import Any


class MinHeap:
    def __init__(self):
        # Initialize the heap as an empty list
        self.heap = []
        # Initialize the sequence as 0
        self._sequence = 0
        # Tuple layout: [0]=priority, [1]=sequence, [2]=item

    # Main Methods
    def peek(self) -> Any:
        # Returns the smallest element in the heap without removing it
        return None if not self.heap else self.heap[0][2]

    def insert(self, item: Any, priority: int = 0):
        self._sequence += 1
        # Inserts an element into the heap
        heappush(self.heap, (priority, self._sequence, item))

    def extract_min(self) -> Any:
        # Removes and returns the smallest element in the heap
        return None if not self.heap else heappop(self.heap)[2]
