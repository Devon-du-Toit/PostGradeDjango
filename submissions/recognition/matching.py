def levenshtein_distance(value_a, value_b):
    previous_row = list(
        range(len(value_b) + 1)
    )

    for i, char_a in enumerate(
        value_a,
        start=1,
    ):
        current_row = [i]

        for j, char_b in enumerate(
            value_b,
            start=1,
        ):
            insertion = current_row[j - 1] + 1
            deletion = previous_row[j] + 1
            substitution = (
                previous_row[j - 1]
                + (char_a != char_b)
            )

            current_row.append(
                min(
                    insertion,
                    deletion,
                    substitution,
                )
            )

        previous_row = current_row

    return previous_row[-1]


def find_best_student_number_match(
    candidates,
    valid_student_numbers,
    max_distance=1,
):
    valid_student_numbers = list(valid_student_numbers)

    # Always prefer an exact match.
    for candidate in candidates:
        if candidate.value in valid_student_numbers:
            return candidate.value

    possible_matches = []

    for candidate in candidates:
        for student_number in valid_student_numbers:
            distance = levenshtein_distance(
                candidate.value,
                student_number,
            )

            if distance <= max_distance:
                possible_matches.append(
                    (
                        student_number,
                        distance,
                        candidate.confidence,
                    )
                )

    if not possible_matches:
        return None

    best_distance = min(
        match[1]
        for match in possible_matches
    )

    closest_numbers = {
        student_number
        for student_number, distance, _ in possible_matches
        if distance == best_distance
    }

    if len(closest_numbers) != 1:
        return None

    return closest_numbers.pop()