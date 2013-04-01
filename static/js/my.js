
$(document).on('click', '.remove-city-link', function (e) {
    $(this).parent().remove();
    $.ajax({
        type: "GET",
        url: "/remove_city/" + $(this).data('cityid'),
        cache: false
    });
    e.preventDefault();
});