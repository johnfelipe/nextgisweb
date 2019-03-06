/* globals define */
define([
    "dojo/_base/declare",
    "./Base",
    "dojo/_base/array",
    "dojo/Deferred",
    "dojo/dom-construct",
    "dijit/form/HorizontalSlider",
    "ngw-pyramid/i18n!webmap"
], function (
    declare,
    Base,
    array,
    Deferred,
    domConstruct,
    HorizontalSlider,
    i18n
) {
    return declare(Base, {
        constructor: function () {
            var tool = this;

            this.label = i18n.gettext("Time slider");
            this.customIcon = "<span class='ol-control__icon material-icons'>date_range</span>";

            var container = domConstruct.create("div", {}, this.display.leftBottomControlPane, "last");
            var label = domConstruct.create("div", {style: "color: white;"}, container, "last");

            this.getDates().then(function (dates) {
                var minDate = dates.length ? Math.min.apply(null, dates) : new Date(null).getTime();
                var maxDate = dates.length ? Math.max.apply(null, dates) : new Date().getTime();
                tool.slider = new HorizontalSlider({
                    minimum: minDate,
                    maximum: maxDate,
                    value: 0.5 * (minDate + maxDate),
                    style: "width: 300px; margin-top: 20px;",
                    intermediateChanges: true,
                    showButtons: false,
                    disabled: true,
                    onChange: function(value) {
                        label.innerHTML = new Date(value).toISOString().slice(0, 10);
                        tool.display.itemStore.fetch({
                            query: {type: "layer"},
                            queryOptions: {deep: true},
                            onItem: function (item) {
                                var cond;
                                var config = tool.display._itemConfigById[tool.display.itemStore.getValue(item, "id")];
                                var minDate = config.minDate && new Date(config.minDate);
                                var maxDate = config.maxDate && new Date(config.maxDate);

                                if (minDate || maxDate) {
                                    if (minDate && maxDate) {
                                        cond = ((new Date(value).getTime() >= minDate.getTime()) &&
                                                (new Date(value).getTime() <= maxDate.getTime()));
                                    } else if (minDate && !maxDate) {
                                        cond = (new Date(value).getTime() >= minDate.getTime());
                                    } else if (maxDate && !minDate) {
                                        cond = (new Date(value).getTime() <= maxDate.getTime())
                                    }
                                    tool.display.itemStore.setValue(item, "checked", cond);
                                }
                            }
                        });
                    }
                }, container);
            });
        },

        getDates: function () {
            var deferred = new Deferred();
            var tool = this;

            tool.display.itemStore.fetch({
                query: {type: "layer"},
                queryOptions: {deep: true},
                onComplete: function (items) {
                    var dates = [];
                    array.forEach(items, function (item) {
                        var config = tool.display._itemConfigById[tool.display.itemStore.getValue(item, "id")];
                        if (config.minDate) { dates.push(new Date(config.minDate).getTime()); }
                        if (config.maxDate) { dates.push(new Date(config.maxDate).getTime()); }
                    });
                    deferred.resolve(dates);
                },
                onError: function (error) {
                    deferred.reject(error)
                }
            });

            return deferred;
        },

        activate: function () {
            this.slider.onChange(this.slider.get("value"));
            this.slider.set("disabled", false);
        },

        deactivate: function () {
            this.slider.set("disabled", true);
        }
    });
});
