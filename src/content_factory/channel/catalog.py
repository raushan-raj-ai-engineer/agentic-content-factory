from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Scene:
    title: str
    narration: str
    values: list[str] = field(default_factory=list)
    active: list[int] = field(default_factory=list)
    detail: str = ""
    code: str = ""
    stage: str = "explain"
    pointers: dict[str, int] = field(default_factory=dict)
    inactive: list[int] = field(default_factory=list)
    comparison: str = ""
    callout: str = ""
    learning_goal: str = ""


@dataclass
class Lesson:
    topic: str
    title: str
    scenes: list[Scene]
    result: object
    code: str
    time_complexity: str
    space_complexity: str
    inputs: dict

    def to_dict(self):
        return asdict(self)


CODES = {
    "binary-search": '''def binary_search(nums, target):
    low, high = 0, len(nums) - 1
    while low <= high:
        mid = (low + high) // 2
        if nums[mid] == target:
            return mid
        if nums[mid] < target:
            low = mid + 1
        else:
            high = mid - 1
    return -1''',
    "two-sum": '''def two_sum(nums, target):
    seen = {}
    for i, value in enumerate(nums):
        need = target - value
        if need in seen:
            return [seen[need], i]
        seen[value] = i
    return None''',
    "move-zeroes": '''def move_zeroes(nums):
    write = 0
    for read in range(len(nums)):
        if nums[read] != 0:
            nums[write], nums[read] = nums[read], nums[write]
            write += 1
    return nums''',
    "palindrome": '''def is_palindrome(text):
    left, right = 0, len(text) - 1
    while left < right:
        if text[left] != text[right]:
            return False
        left += 1
        right -= 1
    return True''',
    "character-frequency": '''def character_frequency(text):
    counts = {}
    for char in text:
        counts[char] = counts.get(char, 0) + 1
    return counts''',
}


TITLES = {
    "two-sum": "Two Sum: remember the missing partner",
    "binary-search": "Binary Search: halve the search space",
    "move-zeroes": "Move Zeroes: preserve the useful order",
    "palindrome": "Palindrome: compare from both ends",
    "character-frequency": "Character Frequency: count with a dictionary",
}


def lesson(topic: str, values=None, target=None, text=None) -> Lesson:
    topic = topic.lower().strip().replace("_", "-").replace(" ", "-")
    topic = {"move-zeros": "move-zeroes", "frequency": "character-frequency"}.get(topic, topic)
    if topic not in CODES:
        raise ValueError("Unsupported topic. Run channel list for supported topics.")

    if topic in ("palindrome", "character-frequency"):
        text = text if text is not None else ("racecar" if topic == "palindrome" else "banana")
        if not isinstance(text, str) or len(text) > 12 or not text.isascii() or any(ord(c) < 32 or ord(c) > 126 for c in text):
            raise ValueError("Use at most 12 printable ASCII characters for the visual lesson.")
        nums = list(text)
    else:
        defaults = {
            "two-sum": [2, 7, 11, 15],
            "binary-search": [2, 5, 8, 12, 16, 23, 38],
            "move-zeroes": [0, 1, 0, 3, 12],
        }
        nums = list(defaults[topic] if values is None else values)
        if len(nums) > 12 or any(type(n) is not int or abs(n) > 999 for n in nums):
            raise ValueError("Use at most 12 integers from -999 through 999.")
        target = (16 if topic == "binary-search" else 9) if target is None else target
        if type(target) is not int or abs(target) > 999:
            raise ValueError("Target must be an integer from -999 through 999.")

    original = nums.copy()
    scenes: list[Scene] = []

    def add(
        title: str,
        narration: str,
        detail: str = "",
        active=(),
        *,
        stage: str = "explain",
        pointers: dict[str, int] | None = None,
        inactive=(),
        comparison: str = "",
        callout: str = "",
        learning_goal: str = "",
    ) -> None:
        scenes.append(
            Scene(
                title=title,
                narration=narration,
                values=[str(x) for x in nums],
                active=list(active),
                detail=detail,
                stage=stage,
                pointers=dict(pointers or {}),
                inactive=list(inactive),
                comparison=comparison,
                callout=callout,
                learning_goal=learning_goal,
            )
        )

    # Start with a learner problem, not a generic welcome. The first seconds
    # should create a reason to watch before definitions appear.
    if topic == "binary-search":
        hook = f"How can we find {target} without checking every value? Binary search uses sorted order to remove half of the remaining search space after each comparison."
        hook_callout = f"Find {target} with fewer checks"
    elif topic == "two-sum":
        hook = f"Can we find two positions that add to {target} without testing every pair? The key is to remember what we have already seen."
        hook_callout = f"Find two values that make {target}"
    elif topic == "move-zeroes":
        hook = "How can we move every zero to the end without disturbing the order of the nonzero values? We can solve it in one pass with two positions."
        hook_callout = "Move zeroes in-place"
    elif topic == "palindrome":
        hook = f"Do we really need to reverse {text!r} to check whether it is a palindrome? Two pointers can prove the answer by comparing mirrored characters."
        hook_callout = "Compare mirrored characters"
    else:
        hook = f"How many times does each character appear in {text!r}? A dictionary lets us count the text in one left-to-right pass."
        hook_callout = "Count every character once"

    add(
        TITLES[topic],
        hook,
        "Worked example → mental model → trace → Python → complexity → edge cases",
        stage="hook",
        callout=hook_callout,
        learning_goal="Understand why the algorithm works before memorizing syntax.",
    )

    # Beginner bridge: define the idea before introducing implementation state.
    if topic == "binary-search":
        add(
            "What is binary search?",
            "Binary search is a searching algorithm for sorted data. Instead of checking values one by one, it starts near the middle and removes the half that cannot contain the answer. Think of opening a paper dictionary near the middle: if your word comes later alphabetically, you ignore the earlier half and continue with the later half.",
            "Linear search: check one by one\nBinary search: compare middle → remove one half\nAnalogy: open a dictionary near the middle",
            stage="theory",
            callout="Sorted order lets one comparison remove many candidates",
            learning_goal="Understand the basic idea and when binary search is appropriate.",
        )
    elif topic == "two-sum":
        add(
            "What problem are we solving?",
            "Two Sum asks us to find two different positions whose values add to a target. A beginner approach checks many pairs. The faster idea is to remember earlier values so each new value can ask whether its required partner has already appeared.",
            f"Need two different indices whose values add to {target}",
            stage="theory",
            callout="Turn repeated pair-checking into lookup",
            learning_goal="Understand the problem before learning the dictionary technique.",
        )
    elif topic == "move-zeroes":
        add(
            "What does in-place mean here?",
            "We want every zero at the end while keeping the nonzero values in their original order. In-place means we modify the same list rather than building a second full result list.",
            "Goal: preserve nonzero order and reuse the original list",
            stage="theory",
            callout="Same list, stable nonzero order",
            learning_goal="Understand the output contract before tracing pointers.",
        )
    elif topic == "palindrome":
        add(
            "What is a palindrome?",
            "A palindrome reads the same from left to right and right to left under the exact comparison rules of this problem. That means mirrored positions should contain the same character.",
            "Mirrored positions must match",
            stage="theory",
            callout="Compare the outside pair, then move inward",
            learning_goal="Understand the property we are trying to prove.",
        )
    else:
        add(
            "What is character frequency?",
            "Character frequency means counting how many times each character appears. A dictionary is useful because it can store one count for each distinct character while we scan the text once.",
            "character → number of occurrences",
            stage="theory",
            callout="One key per distinct character",
            learning_goal="Understand what the frequency map represents.",
        )

    if topic == "binary-search":
        if nums != sorted(nums):
            raise ValueError("Binary search requires a sorted ascending array.")
        low, high = 0, len(nums) - 1
        add(
            "Rule #1: use sorted data",
            f"Before we start, check the most important rule: the values must be sorted. They are sorted here, so binary search is safe to use. Our target is {target}. Low and high simply mark the part of the array where the answer could still be.",
            f"Target = {target}   |   possible range = [{low}, {high}]",
            stage="concept",
            pointers={"LOW": low, "HIGH": high} if nums else {},
            callout="Binary search needs sorted data",
            learning_goal="Know the sorted-data rule before applying binary search.",
        )
        result = -1
        eliminated: set[int] = set()
        while low <= high:
            mid = (low + high) // 2
            add(
                f"Inspect the middle: index {mid}",
                f"The active range is index {low} through {high}. Its middle index is {mid}, where the value is {nums[mid]}. Now compare {nums[mid]} with the target {target}.",
                f"low={low}   mid={mid}   high={high}",
                [mid],
                stage="trace",
                pointers={"LOW": low, "MID": mid, "HIGH": high},
                inactive=sorted(eliminated),
                comparison=f"{nums[mid]} ? {target}",
                callout="One comparison decides which half can be removed",
                learning_goal="Connect low, mid and high to the current search interval.",
            )
            if nums[mid] == target:
                result = mid
                add(
                    "Target found",
                    f"The middle value equals the target. Return index {mid}. If duplicates exist, this version returns a matching index; it does not promise the first occurrence.",
                    f"Return {mid}",
                    [mid],
                    stage="verify",
                    pointers={"MID": mid},
                    inactive=sorted(eliminated),
                    comparison=f"{nums[mid]} == {target}",
                    callout=f"Answer: index {mid}",
                    learning_goal="Verify both the returned index and the value stored there.",
                )
                break
            if nums[mid] < target:
                removed = list(range(low, mid + 1))
                eliminated.update(removed)
                old_mid = mid
                low = mid + 1
                add(
                    "Discard the left half",
                    f"{nums[old_mid]} is smaller than {target}. Because the array is sorted, index {old_mid} and every position to its left are too small. Move low to {low}.",
                    f"Next range = [{low}, {high}]",
                    stage="decision",
                    pointers={"LOW": low, "HIGH": high} if low <= high else {},
                    inactive=sorted(eliminated),
                    comparison=f"{nums[old_mid]} < {target}",
                    callout=f"Discard indices {removed[0]}–{removed[-1]}",
                    learning_goal="Explain why sorted order justifies removing an entire half.",
                )
            else:
                removed = list(range(mid, high + 1))
                eliminated.update(removed)
                old_mid = mid
                high = mid - 1
                add(
                    "Discard the right half",
                    f"{nums[old_mid]} is larger than {target}. Because the array is sorted, index {old_mid} and every position to its right are too large. Move high to {high}.",
                    f"Next range = [{low}, {high}]",
                    stage="decision",
                    pointers={"LOW": low, "HIGH": high} if low <= high else {},
                    inactive=sorted(eliminated),
                    comparison=f"{nums[old_mid]} > {target}",
                    callout=f"Discard indices {removed[0]}–{removed[-1]}",
                    learning_goal="Explain why sorted order justifies removing an entire half.",
                )
        if result == -1:
            add(
                "The interval is empty",
                "Low has moved beyond high, so there is no position left that can contain the target. Return minus one. An empty input reaches this result immediately.",
                "Return -1",
                stage="verify",
                inactive=range(len(nums)),
                comparison="low > high",
                callout="No candidate positions remain",
                learning_goal="Know the termination condition for an unsuccessful search.",
            )
        tc, sc = "O(log n)", "O(1)"
        invariant = "Each unsuccessful comparison removes roughly half of the remaining candidate positions. Repeated halving produces logarithmic time. The loop stores only low, mid and high, so the extra space is constant."
        edge = "Try concrete boundary examples: an empty list with target 16 returns -1; a one-value list [16] returns index 0; [2, 5, 8] with target 7 returns -1; and targets at the first or last position should still be found. With duplicates, this version returns a matching index, not necessarily the first one."

    elif topic == "two-sum":
        seen: dict[int, int] = {}
        result = None
        add(
            "Mental model: remember the complement",
            f"For each value, subtract it from {target}. That gives the partner we need. A dictionary stores values from earlier positions, so we can ask whether that partner has already appeared.",
            f"Target = {target}   |   seen = {{}}",
            stage="concept",
            callout="Need = target − current value",
            learning_goal="Replace pair-by-pair searching with one dictionary lookup per value.",
        )
        for i, value in enumerate(nums):
            need = target - value
            add(
                f"Index {i}: need {need}",
                f"The current value is {value}. Compute {target} minus {value}, which gives {need}. Check the dictionary before storing the current value so we never reuse the same index.",
                f"seen = {seen}",
                [i],
                stage="trace",
                pointers={"READ": i},
                comparison=f"need {need} in seen?",
                callout=f"Looking for {need}",
                learning_goal="Understand why lookup happens before insertion.",
            )
            if need in seen:
                result = [seen[need], i]
                add(
                    "A valid pair",
                    f"The partner {need} was stored at index {seen[need]}. Return indices {seen[need]} and {i}. They are different positions, and their values add to {target}.",
                    f"Return {result}",
                    result,
                    stage="verify",
                    pointers={"A": seen[need], "B": i},
                    comparison=f"{nums[seen[need]]} + {value} = {target}",
                    callout=f"Answer: {result}",
                    learning_goal="Verify the indices are distinct and their values satisfy the target.",
                )
                break
            seen[value] = i
            add(
                "Remember this value",
                f"The partner was not found, so store value {value} at index {i}. Future positions can now use it as a possible partner.",
                f"seen = {seen}",
                [i],
                stage="decision",
                pointers={"READ": i},
                callout=f"Store {value} → index {i}",
                learning_goal="See the dictionary as memory of the prefix already processed.",
            )
        if result is None:
            add(
                "No pair exists",
                "Every position has been processed and no required partner was found. This implementation returns None when there is no solution.",
                "Return None",
                stage="verify",
                callout="No valid pair",
                learning_goal="Recognize the no-solution contract.",
            )
        tc, sc = "Expected O(n)", "O(n)"
        invariant = "Each position is visited once. Dictionary lookup and insertion are constant time on average, so the expected running time is linear. The dictionary can grow with the input size, giving linear extra space."
        edge = "Try concrete cases: [3, 3] with target 6 should use two different indices; [-2, 7] with target 5 should work with a negative number; [5] with target 10 has no valid pair; and [1, 2, 3] with target 99 returns no solution. Verify the sum and distinct indices, not one memorized answer."

    elif topic == "move-zeroes":
        write = 0
        add(
            "Mental model: read and write have different jobs",
            "Read examines every position. Write marks where the next nonzero value belongs. When read finds a nonzero value, swap it into the write position and advance write.",
            "READ scans   |   WRITE marks the next nonzero slot",
            stage="concept",
            pointers={"WRITE": write} if nums else {},
            callout="Preserve nonzero order while compacting",
            learning_goal="Understand the two-pointer invariant before tracing swaps.",
        )
        for read in range(len(nums)):
            value = nums[read]
            add(
                f"Read index {read}",
                f"Index {read} contains {value}. " + ("It is zero, so write stays where it is." if value == 0 else f"It is nonzero, so place it at write index {write} and then advance write."),
                f"read={read}   write={write}",
                [read],
                stage="trace",
                pointers={"READ": read, "WRITE": write},
                comparison=f"{value} != 0 ?",
                callout="Skip zero" if value == 0 else "Place the next nonzero value",
                learning_goal="Track exactly when write moves and when it stays still.",
            )
            if value != 0:
                old_write = write
                nums[write], nums[read] = nums[read], nums[write]
                write += 1
                add(
                    "Array after placement",
                    f"The prefix before index {write} now contains the nonzero values seen so far, in their original relative order. Write moves to the next open position.",
                    f"Placed at {old_write}   |   next write={write}",
                    range(write),
                    stage="decision",
                    pointers={"WRITE": write} if write < len(nums) else {},
                    callout="Invariant: prefix contains processed nonzero values",
                    learning_goal="See why the algorithm is stable for nonzero values.",
                )
        result = nums.copy()
        tc, sc = "O(n)", "O(1)"
        invariant = "Read advances once per input position, so the running time is linear. Write advances only when a nonzero value is found. The list is modified in place, so the extra space is constant."
        edge = "Try concrete cases: [] stays []; [0, 0] stays all zeroes; [1, 2, 3] stays unchanged; and [0, 1, 0, 1] becomes [1, 1, 0, 0]. Verify both the number of zeroes and the original relative order of nonzero values."

    elif topic == "palindrome":
        left, right = 0, len(nums) - 1
        result = True
        add(
            "Mental model: compare mirrored positions",
            "Place one pointer at each end. If the two characters differ, the answer is immediately false. If they match, move inward and test the next mirrored pair.",
            "Exact comparison: case, spaces and punctuation all count",
            stage="concept",
            pointers={"LEFT": left, "RIGHT": right} if nums else {},
            callout="Match from the outside inward",
            learning_goal="Understand the early-exit proof for a mismatch.",
        )
        while left < right:
            equal = nums[left] == nums[right]
            add(
                f"Compare index {left} with {right}",
                f"Compare {nums[left]!r} on the left with {nums[right]!r} on the right. " + ("They match, so move both pointers inward." if equal else "They differ, so the text is not a palindrome."),
                f"{nums[left]!r} == {nums[right]!r}: {equal}",
                [left, right],
                stage="trace" if equal else "verify",
                pointers={"LEFT": left, "RIGHT": right},
                comparison=f"{nums[left]!r} == {nums[right]!r}",
                callout="Match → move inward" if equal else "Mismatch → return False",
                learning_goal="Use mirrored pairs as the invariant.",
            )
            if not equal:
                result = False
                break
            left += 1
            right -= 1
        tc, sc = "O(n)", "O(1)"
        invariant = "Every comparison checks one mirrored pair. A mismatch proves the text is not a palindrome. If the pointers meet or cross, every mirrored pair matched. Only two index variables are needed."
        edge = "Try concrete cases: an empty string and 'a' return true; 'abba' tests an even length; 'racecar' tests an odd length; and 'abca' fails on a mirrored mismatch. 'Aba' is false under this exact comparison because uppercase and lowercase are different."

    else:
        counts: dict[str, int] = {}
        add(
            "Mental model: one visit, one increment",
            "Use a dictionary where each character is a key and its frequency is the value. Scan left to right. Every visit increases exactly one count by one.",
            "Dictionary: character → frequency",
            stage="concept",
            callout="One pass over the text",
            learning_goal="Connect each input character to one dictionary update.",
        )
        for i, char in enumerate(nums):
            counts[char] = counts.get(char, 0) + 1
            add(
                f"Visit index {i}",
                f"The character is {char!r}. Its count becomes {counts[char]}. No other count changes during this step.",
                str(counts),
                [i],
                stage="trace",
                pointers={"READ": i},
                comparison=f"count[{char!r}] = {counts[char]}",
                callout=f"Increment {char!r}",
                learning_goal="See the frequency map evolve one character at a time.",
            )
        result = counts
        tc, sc = "Expected O(n)", "O(k), k distinct characters"
        invariant = "There is one dictionary update per input character, so the expected time is linear. Extra space depends on the number of distinct characters, which is at most the input length."
        edge = "Try concrete cases: an empty string gives an empty dictionary; 'aaa' gives one key with count 3; 'Aa' keeps uppercase and lowercase as separate keys; and 'a a' counts the space too. The sum of all counts must equal the input length."

    add(
        "Verify the result",
        f"For this input, the result is {result}. Before looking at the implementation, replay the final state and make sure it satisfies the problem contract.",
        f"Result: {result}",
        stage="verify",
        callout=f"Verified result: {result}",
        learning_goal="Separate tracing from verification so the result is not accepted blindly.",
    )

    code_narrations = {
        "binary-search": (
            "Now connect the visual trace to the Python code. The variables low and high are the same boundaries you watched on screen, and mid chooses the middle position. When the middle value is smaller than the target, low = mid + 1 is exactly the step that discarded the left half. When it is larger, high = mid - 1 discards the right half. The code is just the visual reasoning written precisely."
        ),
        "two-sum": (
            "Now connect the trace to the code. The dictionary named seen is the memory we built on screen. The line need = target - value calculates the missing partner. Checking need in seen is the lookup step, and storing seen[value] = i makes the current value available to future positions."
        ),
        "move-zeroes": (
            "Now connect the pointers to the code. The read index visits every position, while write marks where the next nonzero value belongs. The swap moves that value into the compacted prefix, and write advances only after a nonzero value is placed."
        ),
        "palindrome": (
            "Now connect the picture to the code. Left and right are the two end pointers. The equality check compares one mirrored pair. A mismatch returns false immediately; otherwise left moves right, right moves left, and the same reasoning repeats."
        ),
        "character-frequency": (
            "Now connect the evolving dictionary to the code. The loop visits one character at a time. counts.get(char, 0) means use the existing count when the character has been seen, otherwise start from zero. Adding one performs the exact increment shown in the trace."
        ),
    }
    scenes.append(
        Scene(
            title="Connect the trace to Python",
            narration=code_narrations[topic],
            code=CODES[topic],
            stage="code",
            callout="Visual step → exact code line",
            learning_goal="Connect each implementation line to the reasoning already shown visually.",
        )
    )

    add(
        "Why the complexity follows",
        invariant,
        f"Time: {tc}\nExtra space: {sc}",
        stage="complexity",
        comparison=tc,
        callout=f"Time {tc}   |   Space {sc}",
        learning_goal="Derive complexity from the work performed by the algorithm.",
    )
    add(
        "Edge cases worth testing",
        edge,
        "Verify the contract, not only the happy path",
        stage="edge-cases",
        callout="Test boundaries and assumptions",
        learning_goal="Think like an engineer: challenge assumptions and boundary conditions.",
    )
    add(
        "Your turn: predict before running",
        "Choose a different small input. Predict the result and at least the next two states before you run the code. If your prediction is wrong, identify which invariant you misunderstood.",
        "Change --values / --target / --text to generate a fresh example",
        stage="practice",
        callout="Predict → run → explain the difference",
        learning_goal="Convert passive watching into retrieval practice.",
    )

    return Lesson(
        topic,
        TITLES[topic],
        scenes,
        result,
        CODES[topic],
        tc,
        sc,
        {"values": original, "target": target, "text": text},
    )
